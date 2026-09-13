# AegisX CLI Manual

This is the operator manual for the current Linux development bundle. It runs AegisX from a source
checkout; it is not yet a standalone signed endpoint package.

## Install once

Required on the machine:

- Linux, Git, and `uv`;
- Python 3.12 (downloaded by `uv` when needed);
- either Docker Engine with Docker Compose, or Podman with `podman-compose`.

From the repository root:

```bash
./scripts/install-aegisx
aegisx doctor
```

The installer places the `aegisx` command in the user environment through `uv tool install`. If the
shell cannot find it, add `$HOME/.local/bin` to `PATH`, restart the shell, then rerun `aegisx doctor`.

## Start and use the console

```bash
aegisx run
```

The launcher finds the checkout, validates a Compose provider, starts PostgreSQL, synchronizes the
API and agent environments, applies Alembic migrations, waits for API readiness, and opens the
terminal Operator Console. The first run may take several minutes while images and Python packages
download.

Console keys:

| Key | Action |
|---|---|
| `1`–`5` | Devices, Events, Detections, Candidates, Incidents |
| `r` | Refresh the bounded read-only view |
| `q` | Quit and clean up launcher-owned processes |

Use `aegisx run --no-ui` for API and agent logs instead of the console. Use `aegisx stop` to stop the
Compose PostgreSQL service. Normal stop does not delete its volume.

## Data status and retention

There are now two separate storage layers:

- **endpoint journal**: the agent first writes each generated Event to private local SQLite;
- **server evidence**: the unchanged Event is then delivered to PostgreSQL for Detection,
  CorrelationCandidate, and Incident processing.

Writing locally happens before the network call. If local persistence fails, that Event is not sent
and the cycle reports degraded coverage. This prevents the server from appearing complete while the
endpoint copy is missing.

Inspect the endpoint journal without Docker, Podman, API, or PostgreSQL:

```bash
aegisx local-data-status
aegisx local-verify
aegisx local-prune --dry-run
```

`local-data-status` reports aggregate counts, event types, delivery states, logical payload bytes,
physical SQLite file bytes, and coverage-gap count. Delivery states mean:

- `PENDING`: safely stored locally but not yet acknowledged by the server;
- `ACKED`: the server accepted it or reported the same UUID as a duplicate;
- `QUARANTINED`: the server permanently rejected that individual Event, so automatic retry stopped
  but the local evidence remains.

`local-verify` parses each Event and checks its UUID, canonical size, and SHA-256 checksum. This finds
accidental corruption. It is **not a digital signature**: an attacker able to rewrite the database
can also recompute an unsigned checksum. A future server-anchored/signed checkpoint is required for
strong tamper evidence.

Local policy version 1 keeps acknowledged data for at least 24 hours (`BULK` observations), 7 days
(`OPERATIONAL` system status), or 30 days (`SECURITY` process/network transitions). `PENDING`,
`QUARANTINED`, and unknown/future event types are never automatically pruned. Review first, then use:

```bash
aegisx local-prune --apply --yes
```

The 256 MiB default is a logical payload quota, configurable with
`AEGISX_LOCAL_TELEMETRY_MAX_BYTES`. SQLite's physical file can be larger because of indexes, WAL,
and reusable pages. Under pressure AegisX removes only already-eligible acknowledged rows, oldest
low-priority data first. If safe pruning cannot make space, it rejects the whole new batch and records
a bounded coverage gap instead of silently deleting protected evidence.

For backup, stop the agent first and copy the complete agent state directory, or use SQLite's online
backup mechanism. Copying only `outbox.sqlite3` while the agent is writing can omit WAL data.

Server-side status and retention still use PostgreSQL:

Inspect aggregate storage first:

```bash
aegisx data-status
aegisx prune --dry-run
```

These commands are read-only. Output contains aggregate row counts and timestamps, not raw event
payloads, command lines, tokens, or metadata.

Retention policy version 1 uses the API-controlled `ingested_at` time:

- process resource and network snapshot observations: 24 hours;
- system status: 7 days;
- known process/network transitions: 30 days;
- unknown future event types: never automatically pruned.

Candidate- or Incident-linked Event/Detection evidence is protected. A dry-run is only a snapshot;
concurrent ingestion can change the later apply count.

Destructive command:

```bash
aegisx prune --apply --yes
```

Run it only after reviewing a fresh dry-run and taking any required backup. It deletes eligible
standalone Events and their standalone Detections in transactions of at most 1,000 Events. A failed
transaction rolls back as a unit; previously completed batches stay committed. It does not delete
Candidates, Incidents, agent identity, credentials, outbox, or quarantine. PostgreSQL may retain the
physical file size until normal vacuuming reuses freed pages.

Development-only full reset:

```bash
aegisx dev-reset --yes
```

This is more destructive than prune: it removes the local development PostgreSQL volume and all
server-side evidence. It is refused outside the development environment or without confirmation.
Agent state remains on disk. Do not use it as normal cleanup.

## Where data lives

- PostgreSQL evidence: named Compose volume `aegisx_postgres_data` (the runtime may prefix the
  project name according to the Compose provider).
- Agent state by default: `$HOME/.local/state/aegisx/`.
- Agent identity and credentials: private files in the agent state directory.
- Endpoint Event journal and delivery state: `outbox.sqlite3` in the same directory. Directory mode
  is `0700`; database and fallback coverage-gap file mode is `0600`.
- Process/network comparison baselines and launcher ownership state: the same private directory.

Set `AEGISX_AGENT_STATE_DIR` to intentionally relocate agent state. Back up both the PostgreSQL
volume/database and the agent state directory for a complete development recovery point. Local
Events are an endpoint journal; PostgreSQL remains the authoritative central source for Detection,
CorrelationCandidate, and Incident records. Selective upload is not implemented: the agent still
sends the same stored Event stream.

## Troubleshooting

### No valid Compose provider

`podman` alone is insufficient. Install `podman-compose`, or install Docker with its Compose plugin.
Then verify:

```bash
podman compose version
aegisx doctor
```

To force a valid provider:

```bash
AEGISX_COMPOSE_COMMAND='podman compose' aegisx doctor
```

On rootless Podman, start its user socket if needed:

```bash
systemctl --user enable --now podman.socket
```

### PostgreSQL port is occupied

Create `.env` from `.env.example`, change both `POSTGRES_HOST_PORT` and the port inside
`DATABASE_URL` to the same free host port, then rerun `aegisx run`.

### PostgreSQL could not be started

Run `aegisx doctor`, then inspect the provider directly:

```bash
podman compose --env-file .env config
podman compose --env-file .env up -d --wait postgres
podman compose --env-file .env logs postgres
```

Use `.env.example` instead of `.env` in those commands when no local `.env` exists.

### Slow or interrupted first run

Rerun `aegisx run`; image and package downloads are cached and resume through their normal tools.
The launcher gives setup commands a bounded 15-minute budget and reports a bounded diagnostic on
failure.

## Current security boundary

The Python agent polls at intervals. It can miss short-lived activity between snapshots, so the
console must not be interpreted as realtime prevention. Missing or ambiguous evidence suppresses
transitions instead of inventing them. A Detection is a deterministic rule match, not automatic
malware attribution. AegisX currently performs no automatic response, isolation, notification, AI
analysis, or web/desktop UI.

A Detection only says a deterministic rule matched evidence. It cannot directly block a process or
network connection. Decision/Policy must justify a future action, and a separate future Response
layer must execute it with approval and audit controls.

A future packaged endpoint release must bundle or install its runtime and service lifecycle and
verify signed artifacts. This development bundle still requires the source checkout and `uv`;
server commands additionally require a working Docker/Podman Compose provider, while `local-*`
commands do not.
