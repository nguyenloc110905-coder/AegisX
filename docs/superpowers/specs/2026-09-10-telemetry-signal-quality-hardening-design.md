# Telemetry Signal Quality Hardening Design

Status: approved in chat on 2026-09-10; implementation not started.

## Goal

Reduce default telemetry volume and false-positive rule matches without weakening evidence semantics. AegisX must distinguish observations, transitions, detections, correlations, and incidents, and the terminal console must state what the agent can and cannot prove.

This is a quality-first patch over the accepted Event -> Detection -> CorrelationCandidate -> Incident foundation. It does not restore the discarded external rule pack and does not introduce AI, response execution, notifications, or production threat attribution.

## Current evidence

The development database audit on 2026-09-10 found:

- 294,278 `process.resource_usage` Events;
- 63,722 `network.connection_observed` Events;
- 24,753 `network.listener_observed` Events and exactly 24,753 `LISTENER_OBSERVED` Detections;
- only 75 `network.listener_opened` Events;
- 6 persisted CorrelationCandidates; and
- 3 Incidents created by test/external policies, not by a policy registered in the current application defaults.

During a fresh ten-minute sample, the current default engine created 90 `LISTENER_OBSERVED` Detections and no other rule ID. This confirms that repeated snapshot evidence, rather than security-relevant transitions, dominates the visible signal.

Historical rows include rule and policy IDs that the accepted source tree cannot currently produce. They remain valid historical database rows but must not be presented as proof that those rules are active. This patch never deletes them automatically.

## Semantic boundaries

- **Event:** a validated technical observation or a transition proved by consecutive complete snapshots.
- **Detection:** a deterministic rule match. It is not automatically an alert, malicious verdict, confidence value, or Incident.
- **CorrelationCandidate:** an evidence-supported relationship between Detections. It is not an Incident.
- **Incident:** a separately promoted workflow object under an explicit policy.
- **Enrollment active:** the device credential is enabled. It is not a liveness or protection claim.
- **Telemetry recent:** the server received authenticated telemetry within a configured interval. It does not prove complete coverage or prevention.

## Default collection policy

The collectors continue to take complete snapshots internally because baseline comparison is required to prove lifecycle transitions. Default network and process-metric transmission changes as follows:

| Evidence | Default emission | Reason |
|---|---:|---|
| `system.status` | enabled | bounded heartbeat and host inventory |
| `process.started` | enabled after baseline | proved process-incarnation transition |
| `process.exited` | enabled after baseline | proved absence from a later complete snapshot |
| `process.resource_usage` | disabled | high-volume operational metric, not a security transition |
| `network.listener_observed` | disabled | repeated snapshot inventory creates noise |
| `network.connection_observed` | disabled | repeated snapshot inventory creates noise |
| network `opened` / `closed` | enabled after baseline | endpoint-presence transition proved by consecutive complete snapshots |

`AgentSettings` gains two explicit booleans:

- `emit_process_resource_usage`, default `false`;
- `emit_network_snapshot_observations`, default `false`.

Operators may opt in to the old snapshot/metric stream for diagnostics. Opt-in does not turn those Events into Detections. Existing caps, private atomic baseline files, incomplete-snapshot behavior, PID-reuse handling, outbox ordering, and retry semantics do not change.

The first complete process or network scan establishes a baseline and may therefore emit only `system.status`. AegisX must not invent starts, exits, opens, or closes from the first snapshot.

## Detection rule change

`LISTENER_OBSERVED` is removed from the default rule registry. Historical rows are retained and remain queryable.

A new `LISTENER_OPENED` rule evaluates only `network.listener_opened`. It validates protocol, canonical local address, bounded port, and optional positive PID. Its semantics are deliberately neutral:

- severity: `low`;
- score contribution: `5`;
- reason: the listener endpoint appeared between two complete snapshots;
- no claim of malware, backdoor, intent, attribution, or successful compromise.

`PROCESS_STARTED` remains informational with contribution zero because it is useful process-identity evidence for correlation. `process.resource_usage`, observed network snapshots, closed transitions, and connection transitions produce no default Detection in this patch.

A legitimate Python development server opening a listener remains a low-score neutral match and must never be described as malware or high risk by this rule alone.

## Correlation compatibility

`PROCESS_LISTENER_ACTIVITY` changes its required evidence from `PROCESS_STARTED + LISTENER_OBSERVED` to `PROCESS_STARTED + LISTENER_OPENED`.

All existing eligibility rules remain unchanged:

- same device;
- same positive PID;
- timezone-aware process `started_at` identity;
- process Event timestamp at or before listener Event timestamp;
- inclusive configured correlation window;
- exactly one eligible process identity inside the window.

Confidence remains `low` because the network transition does not carry process `create_time`; PID association alone cannot prove a permanent process identity. The strategy ID and deterministic key formula remain unchanged. Consequently, a historical Candidate for the same `(strategy_id, device_id, pid, started_at)` prevents a duplicate Candidate after upgrade.

Repeated observations cannot enter the strategy. Repeated complete network snapshots cannot emit another `listener_opened`, so they cannot inflate Candidate evidence or score.

The current Candidate still scores 5 and does not satisfy the Incident Foundation's default score/confidence gate. This patch does not add a production Incident promotion policy merely to populate the dashboard.

## Operator-console truthfulness

The Device table stops labeling `Device.is_active` as runtime activity. It shows:

- `Enrollment`: `enabled` or `disabled`, derived from `is_active`;
- `Telemetry`: `recent`, `stale`, `never`, or `disabled`;
- `Last seen`: the existing authenticated-ingestion timestamp.

`Settings.device_stale_after_seconds` is the single server/console configuration source, default 90 seconds and bounded from 5 to 86,400 seconds. `recent` means `last_seen_at >= now - threshold`; `stale` means an enrolled device has an older timestamp; `never` means no authenticated telemetry was ingested. A disabled enrollment remains `disabled` regardless of timestamp.

The console displays a persistent coverage statement:

> Polling telemetry only; AegisX does not prevent attacks and may miss activity between snapshots.

The Detection view remains named after the persisted domain object, but its help/status text states that Detections are rule matches, not automatic alerts or malware verdicts. The console continues to bound queries and must not expose device token digests or raw command-line payloads in the overview.

## Development-data reset

A separate explicit launcher command, `aegisx dev-reset --yes`, may remove the local Compose PostgreSQL volume so developers can discard polluted demo/test history.

Safety requirements:

- reject unless the selected environment is exactly `development`;
- reject without the literal `--yes` flag;
- refuse while a launcher instance is active;
- operate only through the selected repository Compose project and its named volumes;
- print that all local AegisX PostgreSQL evidence will be unrecoverable;
- never run during install, `run`, `doctor`, migration, or upgrade;
- never delete agent identity, credentials, outbox, or baseline files;
- never run automatically as part of this implementation or its tests.

Tests assert command selection and refusal behavior using controlled runners; verification must not delete the developer's current database.

## Persistence and migration behavior

No relational schema change is required for collection flags, rule registration, or correlation inputs. Existing Event, Detection, Candidate, and Incident rows are append-only historical evidence and remain readable.

New rows after upgrade use the new rule semantics. A historical `LISTENER_OBSERVED` Detection is not rewritten into `LISTENER_OPENED`, because a snapshot cannot retroactively prove a transition. There is no data backfill and no Alembic revision for this patch.

## Failure behavior

- An incomplete or denied process/network snapshot emits no lifecycle transitions and does not replace the last trustworthy baseline.
- Optional snapshot/metric emission does not affect baseline persistence.
- A rule failure preserves the existing authoritative Event/Detection transaction behavior.
- Correlation remains in its nested savepoint; its failure cannot roll back Event/Detection evidence.
- Incident promotion remains in its own savepoint; its failure cannot roll back Event, Detection, or Candidate evidence.
- Console liveness computation is read-only and cannot mutate Device state.
- A rejected development reset performs no Compose mutation.

## Required tests

### Agent

- default process baseline emits no resource samples;
- default start, unchanged, exit, PID reuse, and restart semantics remain truthful;
- resource events return only when explicitly enabled;
- default network baseline/repeated snapshots emit no observed Events;
- default network opened/closed transitions are emitted once;
- observed Events return only when explicitly enabled;
- ambiguous and incomplete snapshots still cannot invent transitions;
- settings defaults and environment overrides are validated.

### API detection and correlation

- `LISTENER_OPENED` matching, irrelevant, malformed, severity, score, and evidence reference;
- a Python development listener remains benign/neutral;
- `network.listener_observed` creates no Detection under the default registry;
- correlation accepts `PROCESS_STARTED + LISTENER_OPENED` and rejects observed-only evidence;
- same-device, PID, window, ambiguity, PID-reuse, score, evidence, and deterministic-key behavior remain covered;
- PostgreSQL ingestion creates one opened-listener Detection and an idempotent Candidate without rewriting historical rows.

### Console and launcher

- enrollment and recent/stale/never labels at exact time boundaries;
- persistent polling-coverage wording;
- secret-safe bounded repository behavior;
- development reset rejects missing confirmation, non-development configuration, active launcher ownership, and failed Compose operations;
- accepted reset constructs only the repository-scoped Compose volume command, tested without executing it against the real database.

### Full verification

- API and PostgreSQL integration tests;
- agent tests;
- launcher and console tests;
- Ruff format/check and strict mypy for all three Python projects;
- Alembic current/heads and migration round-trip verification;
- Docker/Podman Compose config validation;
- real `aegisx run`, refresh, and clean exit smoke test;
- Git whitespace and status checks.

## Explicitly out of scope

- restoring the discarded external detection pack;
- automatic deletion or mutation of existing historical evidence;
- claiming that empty Incident output is an engine failure;
- inventing a production Incident promotion policy;
- whitelist/allowlist semantics;
- detailed forensic drill-down;
- notifications;
- Decision/Policy 6B;
- response or endpoint isolation;
- AI;
- eBPF, BCC, kernel modules, or a Go/Rust agent rewrite;
- signed cross-machine releases.

These are separate milestones because they change security policy, evidence capture, response boundaries, or distribution architecture. The next quality milestone should design a small trustworthy behavioral rule/correlation pack before any production Incident policy. Cross-machine distribution and real-time Rust/eBPF capture require independent designs and validation matrices.

## Files expected to change

- `apps/agent/src/aegisx_agent/config.py`
- `apps/agent/src/aegisx_agent/runner.py`
- `apps/agent/src/aegisx_agent/collectors/process.py`
- `apps/agent/src/aegisx_agent/collectors/network.py`
- agent collector/settings/runner tests
- `apps/api/src/aegisx_api/detection/defaults.py`
- detection listener rule module and tests
- `apps/api/src/aegisx_api/correlation/strategies/process_listener_activity.py`
- `apps/api/src/aegisx_api/services/correlation.py`
- correlation unit and PostgreSQL integration tests
- `apps/api/src/aegisx_api/config.py`
- `apps/api/src/aegisx_api/console/types.py`
- `apps/api/src/aegisx_api/console/repository.py`
- `apps/api/src/aegisx_api/console/main.py`
- `apps/api/src/aegisx_api/console/app.py`
- console tests
- `tools/launcher/src/aegisx_launcher/cli.py`
- `tools/launcher/src/aegisx_launcher/runtime.py`
- launcher tests
- `.env.example`, event/detection/correlation/agent/development documentation, implementation map, and progress log
