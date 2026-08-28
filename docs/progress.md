# Progress

## Milestone 0 — Repository Foundation

Status: complete with Docker access limitation documented below.

### Completed work

- Initialized Git on branch `main`.
- Added repository formatting, ignore, environment, pre-commit, and toolchain policies.
- Added API, agent, web, and shared-contract boundaries without later-milestone code.
- Added PostgreSQL 17 Compose configuration with localhost-only binding, health check, 256 MiB limit, persistent volume, and SELinux-compatible read-only initialization mount.
- Added foundation validation, Make targets, README, and initial technical documentation.

### Tests executed

- `git check-ignore -q .env && test -z "$(git check-ignore .env.example)" && git diff --check` — passed.
- `docker compose --env-file .env.example config --quiet` — passed.
- `docker version --format '{{.Server.Version}}'` — client worked; daemon access denied because the current user is not in group `docker`.
- `podman compose --env-file .env.example up -d --wait postgres` — initially failed because SELinux denied the bind mount; passed after adding the `Z` relabel option.
- `podman compose --env-file .env.example exec -T postgres pg_isready -U aegisx -d aegisx` — passed, accepting connections.
- `podman compose --env-file .env.example exec -T postgres psql -U aegisx -d aegisx -v ON_ERROR_STOP=1 -c 'SELECT 1;'` — passed, returned one row.
- `podman compose --env-file .env.example down` — passed; `aegisx_postgres_data` remained present.
- `make CONTAINER_COMPOSE='podman compose' check` — passed; foundation script, whitespace validation, and Compose parsing all returned exit code 0.

### Known limitations

- Docker runtime commands fail for user `nguyenloc` because `/var/run/docker.sock` is owned by `root:docker` and the user is not a member of `docker`. Rootless Podman was used for successful runtime verification.
- Git identity is now configured locally and verified commits are pushed to `origin/main`.
- Application code and production authentication/TLS do not exist in Milestone 0.

### Technical decisions

- Use a modular monolith and exclude Redis until measured realtime scaling requires it.
- Bind development PostgreSQL to loopback only and preserve data across normal shutdown.
- Support both Docker Compose and rootless Podman Compose through an overridable Make variable.
- Keep planned behavior explicitly labeled in documentation.

### Next milestone

Milestone 1 — Backend Foundation: FastAPI configuration and logging, health/readiness, async SQLAlchemy, Alembic, Device and Event models, validated telemetry ingestion, and tests.

## Milestone 1 — Backend Foundation

Status: complete.

### Completed work

- Added the Python 3.12 `uv` project, validated settings, structured logging, FastAPI factory, and liveness endpoint.
- Added async SQLAlchemy infrastructure plus Device and Event models with evidence and correlation fields.
- Added the explicit `0001_device_event` Alembic migration; application code does not use `create_all()`.
- Added database readiness and Linux device registration with one-time opaque tokens; only token digests are persisted.
- Added bearer device authentication and typed batch ingestion for initial process/system events with UUID idempotency.

### Tests executed

- `pytest` model and migration tests — 3 passed.
- Ruff — passed.
- mypy — passed on 13 source files.
- PostgreSQL Alembic `upgrade head`, `downgrade base`, and second `upgrade head` — passed.
- PostgreSQL inspection — confirmed `alembic_version`, `devices`, and `events` tables.
- Full suite after registration work — 9 passed; Ruff and mypy passed on 18 source files.
- Runtime curl smoke — liveness returned `ok`, readiness returned `ready`, registration returned 201, and PostgreSQL contained the registered device.
- Full suite after ingestion work — 12 passed; Ruff and mypy passed on 20 source files.
- Runtime ingestion smoke — first submission returned `accepted=1`, identical retry returned `duplicates=1`, and PostgreSQL contained one event with promoted PID and executable fields.

### Remaining work

Milestone 1 has no remaining definition-of-done work. API container packaging and production transport/authentication hardening remain later cross-cutting work.

### Next milestone

Milestone 2 — Linux Agent Foundation: device identity, API client, ProcessCollector, SystemCollector, normalization, bounded delivery, logging, and tests.

## Detection Requirements Addendum

Status: incorporated into documentation and deferred to dependency-appropriate milestones.

- Added behavior-first detection families, modular pack boundaries, correlation keys, optional ATT&CK metadata, safe validation metrics, and mandatory benign comparison tests.
- No existing architecture or completed API work required rework.
- Detection packs remain intentionally deferred until process/network/file/authentication/Wi-Fi telemetry dependencies exist and Milestones 4-5 are active.
- Milestone 2 remains active; detection backlog work must not interrupt the Linux agent foundation.

## Milestone 2 — Linux Agent Foundation

Status: complete.

### Completed work

- Stable device UUID and API credentials persisted with file mode `0600`.
- Real Linux SystemCollector and bounded ProcessCollector behind collector interfaces.
- API registration/client, event normalization, batching, and `collect-once` CLI.
- Private bounded SQLite outbox with queue-first delivery and offline recovery.
- HTTP error classification, single-event quarantine isolation, structured cycle logs, and bounded periodic backoff.
- Root Make targets for agent sync, tests, lint, typing, and one-shot execution.

### Tests executed

- Agent suite — 9 passed; Ruff and mypy passed on 12 source files.
- Real one-shot run — accepted 81 events in 478 ms without root.
- PostgreSQL verification — 40 `process.started`, 40 `process.resource_usage`, and one `system.status` event for the demo device.
- Agent suite after outbox work — 13 passed; Ruff and mypy passed on 13 source files.
- Real offline recovery — API down queued 81 events; API recovery flushed 162 old/new events and left zero queued. PostgreSQL contained 80 lifecycle, 80 resource, and two system events.
- Final agent suite — 22 passed; Ruff formatting/lint and mypy passed on 15 source files.

### Remaining work

Milestone 2 has no remaining definition-of-done work. Packaging a systemd unit remains later hardening work.

### Next milestone

Milestone 3 — Network Telemetry: active connections, listening sockets, process association where available, normalized persistence, and a local-listener demonstration.

## Milestone 3 — Network Telemetry

Status: complete.

### Completed work

- Added bounded psutil NetworkCollector for TCP/UDP listeners and active connections.
- Added typed API schemas plus promoted/indexed local/remote address, port, protocol, state, and PID fields.
- Added and applied Alembic migration `0002_network_fields`.
- Included network telemetry in one-shot and continuous agent collection.

### Tests executed

- Agent suite — 25 passed; Ruff and mypy passed on 16 source files.
- API suite — 13 passed; Ruff and mypy passed on 20 source files.
- PostgreSQL migration reached `0002_network_fields` and exposed all six promoted network columns.
- Local listener demo — Python HTTP server on `127.0.0.1:8765` was observed as TCP `network.listener` with the correct PID and LISTEN state.

### Known limitations

- PID association depends on OS visibility and may be unavailable without additional privileges.
- This milestone collects socket state snapshots; packet capture and DNS telemetry are intentionally excluded.

### Next milestone

Milestone 4 — Detection Engine: modular rule registry, centralized scoring, initial explainable process/network signals, persistence, and tests including benign comparisons.
