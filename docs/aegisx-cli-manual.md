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
- Offline pending/quarantine queue: `outbox.sqlite3` in the same directory.
- Process/network comparison baselines and launcher ownership state: the same private directory.

Set `AEGISX_AGENT_STATE_DIR` to intentionally relocate agent state. Back up both the PostgreSQL
volume/database and the agent state directory for a complete development recovery point. Current
telemetry is authoritative in PostgreSQL; local-first Event storage is not implemented yet.

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

A future packaged endpoint release must bundle or install its runtime and service lifecycle, verify
signed artifacts, and define local-first storage explicitly. This development bundle still requires
the source checkout, `uv`, and a working Docker/Podman Compose provider.
