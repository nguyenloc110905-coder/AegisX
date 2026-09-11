# AegisX Data Retention Foundation Design

Date: 2026-09-11
Status: proposed for implementation review

## Goal

Add a safe, explainable maintenance boundary that shows where PostgreSQL evidence volume comes from
and removes expired low-value evidence without damaging CorrelationCandidate or Incident evidence.
This is the first independently testable step before local-first endpoint storage and realtime eBPF.

This milestone does not move authoritative storage to the endpoint. It reduces the current server-side
database safely so the later local-first design starts from an explicit admission and retention policy.

## Measured baseline

The development database measured on 2026-09-11 contains 430,985 Events and is 289 MB. The largest
families are:

| Event type | Rows |
|---|---:|
| `process.resource_usage` | 307,118 |
| `network.connection_observed` | 71,779 |
| `network.listener_observed` | 29,568 |
| all other event types combined | 22,520 |

The same database contains 35,241 Detections, including 29,568 historical `LISTENER_OBSERVED`
matches. Current production defaults no longer emit high-volume resource/snapshot telemetry and no
longer evaluate the historical listener-observed rule. The remaining volume is primarily historical.

There are 8 distinct Event references from CorrelationCandidates and 2 from Incidents. Those small
counts do not weaken the protection rule below: every current or future higher-order evidence
reference remains protected.

## User commands

The installed launcher exposes two new commands:

```text
aegisx data-status
aegisx prune --dry-run
aegisx prune --apply --yes
```

`data-status` and dry-run are read-only. `prune --apply` is refused unless `--yes` is also present.
`--yes` without `--apply` has no destructive effect. The launcher discovers the same project and
environment file as `aegisx run`, requires a valid Compose provider, starts PostgreSQL if necessary,
runs Alembic to the accepted head, invokes the API maintenance CLI, and stops PostgreSQL only when
this launcher invocation started it.

The maintenance output contains bounded aggregate counts only. It never prints Event payloads,
command lines, bearer tokens, token digests, or raw metadata.

## Retention policy v1

Age is measured using `events.ingested_at`, the API-controlled persistence timestamp. Agent-provided
`events.timestamp` is evidence time and is not trusted for storage expiry.

| Event family | Retention | Rationale |
|---|---:|---|
| `process.resource_usage` | 24 hours | opt-in operational metric, not a security transition |
| `network.listener_observed` | 24 hours | opt-in point-in-time snapshot |
| `network.connection_observed` | 24 hours | opt-in point-in-time snapshot |
| `system.status` | 7 days | recent health history; current state also exists on Device |
| supported process/network transition events | 30 days | bounded investigation history |
| unknown or future event types | no automatic expiry | fail closed until explicitly classified |

Supported transition events in policy version 1 are `process.started`, `process.exited`,
`network.listener_opened`, `network.listener_closed`, `network.connection_opened`, and
`network.connection_closed`.

The cutoff is inclusive: a row is expired when `ingested_at <= evaluation_time - retention`.
One UTC `evaluation_time` is captured at command start and reused for the complete dry-run or apply.

Retention values are code-owned policy constants with stable policy version `1`. Environment
overrides are deliberately excluded from the first milestone so operators cannot silently weaken
evidence retention. Later local-first storage may make policy configuration explicit and audited.

## Protected evidence

An expired Event must not be deleted when any of these conditions is true:

1. the Event is directly present in `correlation_candidate_events`;
2. the Event is directly present in `incident_events`;
3. a Detection sourced from the Event is present in `correlation_candidate_detections`;
4. a Detection sourced from the Event is present in `incident_detections`.

These tests protect direct and indirect higher-order evidence. Candidate and Incident rows,
association rows, status transitions, and their referenced evidence are never retention targets in
this milestone.

An expired Event may have unpromoted Detections. Apply deletes those Detection rows before deleting
their source Event. This deliberately removes obsolete standalone rule matches such as historical
`LISTENER_OBSERVED` noise. It does not change the meaning of a surviving Detection or higher-order
object.

## Status report

`aegisx data-status` reports:

- PostgreSQL database size;
- total Event, Detection, CorrelationCandidate, and Incident counts;
- count plus oldest/newest `ingested_at` for each Event type;
- count of Candidate/Incident-protected Events;
- current retention policy version.

`aegisx prune --dry-run` reports, per classified Event type:

- cutoff timestamp;
- expired row count;
- protected expired row count;
- deletable Event count;
- unpromoted Detection count that apply would delete.

It also reports totals. Counts are an evaluation-time snapshot, not a reservation. Concurrent
ingestion after the report may change a later apply result.

## Apply algorithm and transactions

Apply processes at most 1,000 Events per transaction:

1. select one ordered batch of expired, unprotected Event IDs for one policy family;
2. lock only those Event rows using PostgreSQL `FOR UPDATE SKIP LOCKED`;
3. re-check all protection predicates inside the batch transaction;
4. delete unpromoted Detections whose `source_event_id` is in the selected batch;
5. delete the selected Events;
6. commit the batch and continue until no eligible rows remain.

A failed batch rolls back completely. Earlier committed batches remain deleted and the command exits
non-zero with the number of already committed Event and Detection deletions. Retrying is safe and
continues from remaining eligible rows. No partially deleted Event/Detection pair can survive a
single batch transaction.

Concurrent ingestion is not blocked globally. `SKIP LOCKED` avoids waiting on rows used by another
transaction. Because only rows older than fixed cutoffs are eligible, new ingestion cannot enter the
current command's retention window.

Normal PostgreSQL autovacuum can reuse deleted pages. This command does not run `VACUUM FULL`, shrink
the database file synchronously, or take an exclusive table rewrite lock. `data-status` therefore
distinguishes logical row reduction from physical database file size.

## Schema change

Alembic `0006_event_retention_index` adds:

```text
ix_events_event_type_ingested_at (event_type, ingested_at)
```

The index supports policy-family cutoff scans. The migration changes no Event, Detection,
CorrelationCandidate, or Incident semantics and adds no deletion cascade.

## Module boundaries

- `aegisx_api.maintenance.retention_policy` owns immutable policy version 1 and event-family TTLs.
- `aegisx_api.maintenance.retention_service` owns read-only statistics, eligibility queries, and
  bounded transactional pruning.
- `aegisx_api.maintenance.cli` renders bounded operator output and exit codes; it contains no SQL.
- `aegisx_launcher.runtime` owns Compose lifecycle and invokes the maintenance CLI through argv.
- `aegisx_launcher.cli` parses `data-status` and `prune` safety flags.
- `docs/aegisx-cli-manual.md` becomes the new-user command manual and is updated in every later CLI
  milestone.

The HTTP telemetry route, Detection Engine, Correlation Engine, and Incident Service do not call the
retention service. Pruning is an explicit maintenance operation only.

## Required tests

Unit tests must prove:

- exact policy version, event families, and inclusive UTC cutoffs;
- unknown event types fail closed and are not targets;
- launcher parsing and refusal of `--apply` without `--yes`;
- `data-status` and dry-run cannot invoke a destructive service method;
- output omits payload, metadata, command line, and token material;
- launcher preserves an already-running PostgreSQL service and cleans up only one it started;
- timeout/provider failures return bounded diagnostics.

Real PostgreSQL integration tests must prove:

- each TTL boundary just before, exactly at, and just after cutoff;
- unreferenced expired metric/snapshot/status/transition deletion;
- recent rows survive;
- unknown event types survive;
- standalone Detection deletion occurs before its Event;
- direct Candidate Event evidence survives;
- direct Incident Event evidence survives;
- Candidate-linked Detection and its source Event survive;
- Incident-linked Detection and its source Event survive;
- Candidate, Incident, and status-transition counts do not change;
- duplicate apply is idempotent;
- a forced failure rolls back the current batch;
- Alembic upgrade/downgrade/upgrade verifies the new index.

The implementation is complete only after API, agent, launcher, PostgreSQL integration, Ruff,
strict mypy, Alembic, Compose validation, and whitespace checks pass. A development dry-run is shown
to the user before any real development-data deletion. Actual deletion requires a second explicit
user instruction after reviewing that dry-run output.

## New-user manual

`docs/aegisx-cli-manual.md` starts in this milestone and documents:

- prerequisites and one-time installation;
- `aegisx run`, `doctor`, `stop`, and `dev-reset`;
- terminal-console keys;
- `data-status` and prune safety workflow;
- where identity, credentials, outbox, PostgreSQL data, and later local telemetry live;
- backup and recovery warnings;
- current polling/realtime coverage limitations;
- troubleshooting Docker/Podman provider, occupied port, PATH, and slow first-run downloads;
- exact distinction between development bundle and future packaged endpoint release.

Examples never embed real credentials. Destructive commands are visually and textually identified.

## Out of scope

- moving authoritative Event/Detection/Incident storage to endpoint SQLite;
- automatic scheduled pruning;
- Candidate or Incident retention;
- legal hold, archival, backup automation, or secure erase;
- realtime eBPF collection or Go-agent work;
- AI, response execution, notifications, web UI, and new detection packs;
- `VACUUM FULL` or automatic deletion of unknown event families.

## Known limitations

- Physical PostgreSQL file size may not fall immediately after row deletion even though reusable
  space and query volume improve.
- Explicit manual pruning means unattended deployments can still grow until scheduled maintenance is
  designed.
- Candidate evidence is retained indefinitely in this milestone even when no Incident is created.
- This server-side policy is transitional. Local-first endpoint storage requires a separate approved
  design covering authority, synchronization, encryption, retention, and failure semantics.
