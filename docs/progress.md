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
- Pre-alignment PostgreSQL verification — 40 legacy snapshot events then named `process.started`, 40 `process.resource_usage`, and one `system.status` event for the demo device.
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
- Pre-alignment local listener demo — Python HTTP server on `127.0.0.1:8765` was observed under the former `network.listener` name with the correct PID and LISTEN state.

### Known limitations

- PID association depends on OS visibility and may be unavailable without additional privileges.
- This milestone collects socket state snapshots; packet capture and DNS telemetry are intentionally excluded.

### Next milestone

Alignment Patch — required before Milestone 4.

## Alignment Patch

Status: complete. Milestone 4 has not begun.

### Completed work

- Persisted a private process baseline keyed by `(PID, create_time)`; the initial scan creates only a baseline and later scans emit `process.started` solely for newly observed identities.
- Renamed socket snapshot evidence to `network.listener_observed` and `network.connection_observed`; no opened/closed transition is claimed.
- Made `telemetry_batch_limit` the authoritative runtime ingestion bound instead of retaining a contradictory schema constant.
- Added FastAPI shutdown disposal for async database engine resources.
- Added an automated PostgreSQL integration test covering real Device registration, authenticated Event ingestion, typed/promoted persistence, and cleanup.
- Retained SQLite tests for fast isolation while adding dialect-level PostgreSQL coverage.

### Verification

- PostgreSQL Alembic upgrade reached head through the asyncpg/PostgreSQL path.
- PostgreSQL Device/Event integration test passed against the healthy Compose service.
- Full test, Ruff, mypy, migration, and integration results are recorded in the completion report for this patch.

### Next milestone

Milestone 4 — Detection Engine. It remains intentionally unstarted until this patch is reviewed.

## Milestone 4 — Detection Engine Foundation

Status: foundation and first rule set implemented; later detection packs are intentionally excluded.

### Completed work

- Added a typed `DetectionRule` protocol, independently testable process/listener rules, duplicate-safe indexed `RuleRegistry`, rule-agnostic `DetectionEngine`, immutable rule/result values, and deterministic clamped scoring.
- Implemented `PROCESS_STARTED` as informational with contribution 0 and `LISTENER_OBSERVED` as low severity with contribution 5.
- Deferred `HIGH_RESOURCE_USAGE` because a single current sample cannot prove sustained abuse.
- Added `Detection` persistence and Alembic `0003_detection_foundation` with Device/source-Event foreign keys, evidence UUIDs, bounded score, reason, severity, and query indexes.
- Extracted telemetry mapping, deduplication, detection evaluation, and atomic persistence into `TelemetryIngestionService`; the FastAPI route no longer owns detection logic.
- Added rule match/non-match/malformed/evidence tests, registry/engine/scoring tests, a benign Python development-listener test, model/migration tests, duplicate-ingestion coverage, and PostgreSQL Event/Detection integration coverage.

### Scope boundary

No correlation, incidents, AI, notifications, UI, ransomware, brute-force, port-scan, persistence, DNS, or Wi-Fi detection was added.

### Verification

- API suite with PostgreSQL integration enabled — 29 passed.
- Agent suite — 25 passed.
- API and agent Ruff format/lint — passed.
- API mypy — passed on 33 source files; agent mypy — passed on 16 source files.
- PostgreSQL Alembic upgrade/current/heads — `0003_detection_foundation (head)`.

## Milestone 5A — Correlation Engine Foundation

Status: implemented as one deterministic, evidence-first Candidate strategy; incident workflow remains unimplemented.

### Completed work

- Added a typed, registry-indexed correlation engine and the `PROCESS_LISTENER_ACTIVITY` strategy over persisted `PROCESS_STARTED` and `LISTENER_OBSERVED` Detections.
- Uses the canonical process identity `(device_id, pid, started_at)`, an inclusive configured window, and an exact-one-eligible-identity rule to reject ambiguous relationships and old PID reuse outside the window.
- Added `CorrelationCandidate` persistence under Alembic `0004_correlation_foundation`, including relational Detection/Event evidence and a globally unique deterministic SHA-256 key.
- Added idempotency: one immutable Candidate per process identity; duplicate retries/repeated listener snapshots do not append evidence or inflate the score.
- Integrated correlation after Event/Detection flush in a nested savepoint. A correlation-only failure rolls back Candidate work, logs the failure, and still commits valid authoritative Event/Detection evidence.
- Kept the behavior neutral: the current pair is low confidence with score 5; it associates a listener snapshot with a recent process identity and does not label it malicious, newly opened, or an Incident.

### Known limitations

- Candidate creation intentionally loses later listener/repeated-snapshot timeline detail until correlation lifecycle semantics are designed.
- There is no Candidate API, background reconciliation after a correlation-only failure, device-risk aggregate, incident conversion, AI, notification, or UI behavior.
- The correlation failure log currently lists every accepted Event ID in its triggering batch, including accepted Events without a Detection.
- The service currently persists a generic hardcoded reason for the first strategy; future strategies need a result-level reason contract. The model relationship test also needs a fresh-session round-trip assertion rather than relying on the current SQLAlchemy identity map.

### Verification

- API suite with PostgreSQL integration enabled — 51 passed, including the real PostgreSQL Candidate flow.
- Agent suite — 25 passed.
- API and agent Ruff format and lint — passed.
- API mypy — passed on 43 source files; agent mypy — passed on 16 source files.
- PostgreSQL Alembic `upgrade head`, `current`, and `heads` — `0004_correlation_foundation (head)`.

## Milestone 5B — Telemetry Fidelity & Operational Hardening

Status: in progress; Tasks 1-2 complete.

### Task 1 — Development environment

- Repaired the malformed PostgreSQL `volumes` entry in `compose.yaml` without changing the service's ports, credentials, health check, resource limit, security options, or named-volume lifecycle.
- `docker compose --env-file .env.example config --quiet` passed and the rendered configuration contains both the named PostgreSQL data volume and read-only SELinux-labelled initialization bind mount.
- Docker runtime access remains unavailable to user `nguyenloc`: `/var/run/docker.sock` is owned by `root:docker` and the user is not a member of `docker`.
- Rootless `podman compose --env-file .env.example up -d --wait postgres` reported the service healthy; `pg_isready` accepted connections and `SELECT 1 AS compose_postgres_ok` returned one row.

### Task 2 — Truthful process exits

- Added `process.exited` to schema version 1. It carries the prior incarnation's positive PID and required `started_at`; the Event timestamp records when absence was observed rather than claiming an exact kernel exit time.
- Lifecycle state now stores versioned `(PID, create_time)` records and writes them with private mode `0600`, file/directory synchronization, and atomic replacement. Existing version-1 baselines remain readable.
- Starts and exits require complete consecutive snapshots. Enumeration failure, lookup races/access denial, or missing `create_time` suppress lifecycle transitions and preserve the prior baseline; resource observations from readable records may still be emitted.
- The collector continues scanning identities after the detailed-output cap, preventing `max_processes` from manufacturing exits. PID reuse emits an exit for the old incarnation and a start for the new one.
- Focused verification: process collector `9 passed`; telemetry API `10 passed`; agent/API Ruff checks passed; strict agent mypy passed on 16 source files and API mypy passed on 43 source files.

### Scope boundary

Incident, AI, UI, notifications, advanced attack detection packs, DNS, Wi-Fi, and packaging/onboarding UX remain unstarted.
