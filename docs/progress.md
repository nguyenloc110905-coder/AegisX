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

Status: complete and verified.

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

### Task 3 — Network state transitions

- Retained snapshot-safe listener/connection observed events and added endpoint-presence `network.listener_opened`, `network.listener_closed`, `network.connection_opened`, and `network.connection_closed` events.
- Canonical listener identity is `(protocol, local_ip, local_port)`; connection identity adds `(remote_ip, remote_port)`. IPs are canonicalized. PID and socket state remain attributes because their OS visibility can vary.
- The first complete snapshot establishes a private atomic baseline. Only complete consecutive snapshots generate transitions; repeated snapshots are idempotent, while collection errors or malformed addresses retain the prior baseline.
- Duplicate canonical identities remain observable but cannot generate an opened event with an arbitrary PID; state records the endpoint without process attribution. Observed and transition outputs are separately bounded, and the full identity snapshot is still persisted.
- Open/closed means endpoint presence changed between collector snapshots, not a precise kernel timestamp or proof of a TCP handshake. Missing process `create_time` prevents process-incarnation attribution but not endpoint identity.
- Focused verification: network collector `11 passed`; all four network transition API cases passed; agent/API Ruff checks and strict mypy passed.

### Task 4 — Async outbox boundary

- Added `AsyncOutbox`, which opens SQLite and runs every queue operation through `asyncio.to_thread`; the runner now awaits enqueue, peek, acknowledge, quarantine, counts, and close.
- One async lock serializes the shared SQLite connection. Cancellation waits for an in-flight worker call before releasing the lock, preventing a cancelled coroutine from allowing overlapping connection access.
- The synchronous `Outbox` remains the single owner of schema, sequence ordering, UUID idempotency, bounded eviction, quarantine transactions, and persistence across restarts; no new service or infrastructure was introduced.
- Focused outbox/runner verification passed `10` tests, including real ordering/idempotency/quarantine behavior, worker-thread execution, serialization, and cancellation safety. Ruff and strict mypy passed.

### Task 5 — Correlation operational observability

- Correlation evaluation/persistence semantics remain unchanged. The service now exposes only the selected strategy IDs needed for observability.
- After the authoritative outer commit, ingestion emits one bounded `correlation_outcome` record with strategy IDs, safe device ID, outcome, evidence commit status, and candidate count or exception-class failure category.
- Failure logs set `evidence_committed=true` only after Event/Detection commit succeeds. An outer-commit failure emits no false survival claim.
- Removed accepted Event UUID lists and avoided tokens, command lines, raw telemetry, metadata, exception messages, and payload-bearing stack output.
- Focused verification passed four outcome/failure-boundary cases; API Ruff and strict mypy passed.

### Final verification

- API suite with real PostgreSQL integration enabled: `59 passed`.
- Agent suite: `43 passed`.
- API Ruff format/check: 59 files formatted and lint-clean; strict mypy passed on 43 source files.
- Agent Ruff format/check: 24 files formatted and lint-clean; strict mypy passed on 16 source files.
- Alembic on an isolated PostgreSQL database: upgrade `base -> 0004_correlation_foundation`, current/heads at `0004`, downgrade `0004 -> base`, and second upgrade/current to `0004` all passed. Milestone 5B adds no relational schema and requires no new migration.
- Development PostgreSQL remained healthy and accepted `SELECT 1`; the isolated migration database was dropped after verification.
- `docker compose --env-file .env.example config --quiet`, foundation checks, `git diff --check`, and final scope/status checks passed. Docker daemon runtime remains unavailable to the current non-`docker` user, so runtime health was verified through rootless Podman.
- Incident, AI, UI, notifications, advanced attack detection packs, DNS, Wi-Fi, and packaging/onboarding UX were not started.
- Final self-review added a regression guard that separately caps `process.exited` output without truncating the identity snapshot; excess exits are intentionally omitted rather than replayed later with stale evidence.

### Scope boundary

Incident, AI, UI, notifications, advanced attack detection packs, DNS, Wi-Fi, and packaging/onboarding UX remain unstarted.

## Milestone 6A — Incident Foundation

Status: implemented and unit-verified; PostgreSQL integration tests require `AEGISX_TEST_POSTGRES_URL`.

### Completed work

- Added `Incident` and `IncidentStatusTransition` SQLAlchemy models with full check constraints (status, disposition, severity, risk, version, evidence bounds, closed_at invariant, resolved-disposition invariant).
- Added association tables `incident_correlation_candidates`, `incident_detections`, `incident_events` with cascade deletes; candidate is uniquely attachable to exactly one Incident.
- Added Alembic migration `0005_incident_foundation` (after `0004_correlation_foundation`); no active-group unique index added as per approved spec.
- Added `apps/api/src/aegisx_api/incident/policies.py` — `IncidentDecision` dataclass, abstract `IncidentPromotionPolicy`, and `IncidentPolicyRegistry` with duplicate-guard registration and thread-safe clear.
- Added `apps/api/src/aegisx_api/services/incident.py` — `IncidentService.process_candidate()` implementing the full approved pipeline: confidence/score gate → policy lookup → `evaluate()` → idempotency check → advisory-lock acquisition with 2-second bounded timeout → sliding-window grouping query → attach-to-existing or create-new with audit transition → structured observability.
- Advisory lock key is derived from `grouping_key` SHA-256 → first 8 bytes → signed 64-bit big-endian integer. Collisions only serialize unrelated promotions; all DB filtering uses the full 64-char `grouping_key` string.
- `TelemetryIngestionService` extended: accepts `IncidentService`, calls `process_candidate()` per candidate in its own savepoint. A failure in the Incident savepoint never rolls back the already-committed `CorrelationCandidate`.
- `Device` model updated with `incidents` relationship.
- Added 26 unit tests in `tests/incident/test_incident_service.py` covering: policy registry, no-policy gate, low-confidence gate, low-score gate, never-promote gate, severity computation, hash-to-lock-id determinism and range, collision identity safety.
- Added 2 PostgreSQL integration tests in `tests/integration/test_postgres_incident.py` (skipped without DB): incident creation + in-window attachment + out-of-window new episode; savepoint failure preserves Candidate.

### PROCESS_LISTENER_ACTIVITY status

- No production promotion policy added for `PROCESS_LISTENER_ACTIVITY`.
- The candidate remains low confidence, aggregate score 5, and will NOT automatically create an Incident.

### Scope boundary at 6A acceptance

AI Investigator, UI, notifications, response actions, background reconciliation, packaging, and Milestone 6B+ work had not started when 6A was accepted. The developer bundle documented below was added afterward; AI was subsequently removed from the roadmap.

### Verification

- API suite: 84 passed, 3 skipped (PostgreSQL integration skipped without `AEGISX_TEST_POSTGRES_URL`).
- Agent suite: unchanged, 43 passed.
- API Ruff format/check: clean on 46 source files.
- API mypy strict: clean on 46 source files.
- Alembic: migration `0005_incident_foundation` is the single head.

## One-Command Developer Bundle

Status: implemented and smoke-tested.

### Completed work

- Preserved the rejected external AI/Decision/detection experiment on local branch `rescue/ai-work-20260910`; `main` remains based on the accepted 6A implementation.
- Added the dependency-free `aegisx` launcher package plus one-time `scripts/install-aegisx` editable installation.
- Added repository/environment discovery, safe Compose argv handling, Docker-to-Podman fallback, automatic user `podman.socket` startup, PostgreSQL readiness, dependency sync, Alembic migration, API readiness gating, host-agent startup, child supervision, and ownership-aware cleanup.
- Added private atomic single-instance state with live PID rejection and instance-ID cleanup protection.
- Removed AI Investigator from the active roadmap and current-product documentation. No AI provider dependency or implementation exists on `main`.
- Corrected the launcher's readiness target from the initially tested wrong `/api/v1/health/ready` path to the actual `/health/ready` endpoint using a red/green regression test.
- Removed the stale, empty `action_decisions` table left by the external experiment and restored the development database marker from `0006_decision_foundation` to accepted head `0005_incident_foundation`. A recoverable PostgreSQL custom-format backup is stored at `/home/nguyenloc/.local/state/aegisx/backups/aegisx-pre-0006-cleanup-20260910.dump`.

### Runtime smoke evidence

- Installed executable resolved as `/home/nguyenloc/.local/bin/aegisx`.
- `aegisx --help` and `aegisx doctor` succeeded from `/tmp`.
- Final real launch rejected inaccessible Docker, selected rootless Podman, reached PostgreSQL healthy, migrated to `0005_incident_foundation`, returned HTTP 200 from `/health/ready`, and delivered an agent cycle with 264 accepted events, zero queued, and zero quarantined.
- `Ctrl+C` stopped Uvicorn and the agent, removed launcher ownership state, and preserved the PostgreSQL service that was already running.

### Final verification

- API suite against an isolated real PostgreSQL database: `102 passed`.
- Agent suite: `43 passed`; launcher suite: `39 passed`.
- API, agent, and launcher Ruff format/check passed; strict mypy passed on 46, 16, and 7 source files respectively.
- Alembic `current` and `heads` both reported `0005_incident_foundation (head)` after the suite's PostgreSQL downgrade/upgrade round trip.
- Docker Compose and Podman Compose configuration validation, repository foundation checks, and `git diff --check` passed.
- Fixed a 6A verification defect: the advisory-lock timeout integration test now uses a valid shared device and requires the PostgreSQL `statement_timeout` database error instead of accepting any unrelated exception.
- The isolated verification database was dropped after testing. Final launcher shutdown left no API/agent child process or launcher state file.

### Scope boundary

This bundle does not change telemetry, Detection, CorrelationCandidate, Incident, or scoring semantics. Decision/Policy, response execution, UI, notifications, new detection packs, and production eBPF CO-RE deployment remain separate work.

## Terminal Operator Console

Status: implemented and smoke-tested.

### Completed work

- Recovered only the visual intent of the discarded Textual prototype; removed its Gemini/AI wording, nonexistent `Incident.decisions` dependency, fake incidents, and unsafe unbounded ORM access.
- Added a read-only console repository that returns bounded immutable display records and counts for Devices, Events, Detections, CorrelationCandidates, and Incidents. Device token digests and raw Event payloads are not exposed.
- Added a five-tab Textual console with number-key navigation, manual `r` refresh, bounded failure messages, and `q` exit.
- `aegisx run` now starts API/agent quietly and runs the console in the foreground. `aegisx run --no-ui` preserves raw log mode. Console exit or interruption triggers the existing ownership-aware process cleanup.
- Fixed launcher child-process session handling after a detached TUI left mouse-report escape sequences reaching Bash as bogus commands. Launcher children now remain in the launcher's foreground terminal process group, with a real process-group regression test.

### Runtime smoke evidence

- From `/tmp`, `aegisx run` selected rootless Podman after inaccessible Docker, opened `AegisX — Operator Console`, and loaded current PostgreSQL counts and Device rows.
- Sending `q` returned exit code 0, removed launcher state, and left no API, agent, or console child process.
- After the session fix, an end-to-end `aegisx run` accepted `r`, refreshed to current PostgreSQL counts, then accepted `q`, returned exit code 0, restored Textual terminal modes, and left no API, agent, or console child process.

### Verification

- API suite against isolated PostgreSQL: `105 passed`; agent suite: `43 passed`; launcher suite: `41 passed`.
- API, agent, and launcher Ruff format/check passed; strict mypy passed on 51, 16, and 7 source files respectively.
- Console-focused repository and Textual pilot coverage passed 3 tests, including refresh and secret-safe failure output.
- Launcher regression verification passed 42 tests; launcher Ruff and strict mypy remained clean.
- Compose validation, foundation validation, Alembic current/heads, and whitespace checks passed. The isolated console verification database was removed afterward.

### Scope boundary

This is a local terminal interface, not a web or desktop UI. Cross-machine signed/checksummed release packaging remains the next packaging stage. AI, Decision/Policy, response actions, notifications, and new Incident promotion behavior were not added.

## Telemetry Signal Quality Hardening

Status: implemented and verified on the feature branch.

### Quiet, truthful collection defaults

- `process.resource_usage`, `network.listener_observed`, and
  `network.connection_observed` agent output is disabled by default. Explicit environment settings
  can opt back into these high-volume observations without weakening private baseline comparison.
- The first complete process/network collection establishes baselines without fabricating lifecycle
  transitions. Later `started`/`exited` and `opened`/`closed` Events still require trustworthy
  consecutive snapshots and remain enabled by default.
- A two-cycle real-agent audit using isolated agent state produced only two `system.status`, two
  truthful `process.exited`, and one `network.connection_opened` Event. It produced zero resource or
  network observation Events and zero Detections. The exact audit Device and temporary state were
  removed afterward; existing development evidence was not reset.

### Detection and correlation

- Replaced the default `LISTENER_OBSERVED` rule with `LISTENER_OPENED` over
  `network.listener_opened`. It remains low severity with deterministic contribution 5 and neutral
  wording. Historical and opt-in listener observation Events persist without a default Detection.
- `PROCESS_LISTENER_ACTIVITY` now requires `PROCESS_STARTED` plus `LISTENER_OPENED`. Its inclusive
  time window, process identity, one-Candidate key, low confidence, score calculation, savepoint,
  and persistence semantics are unchanged. Repeated unchanged snapshots cannot create a Candidate.

### Console and development operations

- The Device table separates enrollment from telemetry status. Telemetry is `recent` at the exact
  configured boundary, then `stale`; never-seen and disabled devices are explicit. The default
  threshold is 90 seconds and is bounded from 5 to 86,400 seconds.
- The terminal console permanently warns that polling may miss activity and that AegisX does not
  prevent attacks. Rule matches are explicitly not automatic alerts.
- Added `aegisx dev-reset --yes`. It refuses missing confirmation, non-development or malformed
  environment selection, missing Compose, provider failure, and a concurrent launcher. Successful
  execution removes only Compose PostgreSQL volumes; agent identity/outbox state is preserved. The
  destructive command was not invoked during verification.

### Verification

- API: `109 passed` with all 17 PostgreSQL integration tests enabled on an isolated database.
- Agent: `47 passed`; launcher: `52 passed` with isolated launcher state.
- API, agent, and launcher Ruff format/check passed. Strict mypy passed on 51, 16, and 7 source
  files respectively.
- Alembic isolated PostgreSQL `upgrade head`, `current`, and `heads` reached
  `0005_incident_foundation (head)`. The isolated database was dropped afterward.
- Docker Compose and Podman Compose configuration validation and `git diff --check` passed. A real
  feature-branch `aegisx run` selected Podman, rendered the coverage warning and priority recency
  columns, refreshed on `r`, exited on `q`, restored terminal modes, removed launcher ownership
  state, and left no API/agent/console child. PostgreSQL remained healthy.

### Remaining limitations and scope

- Polling can miss short-lived activity between snapshots. Missing permissions, malformed socket
  data, or process races deliberately suppress transitions instead of guessing.
- PID is not part of canonical socket identity and listener evidence lacks process `create_time`, so
  the current process/listener Candidate remains low confidence.
- Per-listener Candidate timeline detail, background reconciliation, retention, cross-machine signed
  packaging, service installation, Decision/Policy, response execution, notifications, advanced
  detection packs, and web/desktop UI remain unimplemented. AI remains removed from the roadmap.
- No Incident policy was added or changed; the low-confidence score-5 Candidate still does not
  automatically create an Incident.

## Cross-machine Podman compatibility hotfix

Status: implemented after a clean Fedora 44 installation exposed the portability defect.

- Qualified the PostgreSQL image as `docker.io/library/postgres:17-alpine`. Rootless Podman with
  enforced short-name resolution can now pull it non-interactively instead of failing because no
  registry can be selected without a TTY.
- Added a foundation regression check that rejects a return to the ambiguous short image name.
- A separate local `.env` may move `POSTGRES_HOST_PORT` and `DATABASE_URL` together when port 5432
  is already occupied; the existing system PostgreSQL service does not need to be stopped.
- Slow first-time dependency downloads now have a 15-minute setup budget instead of the previous
  fixed five minutes. A setup timeout becomes a bounded launcher failure with a clear diagnostic
  and cleanup rather than leaking a Python `TimeoutExpired` traceback.
- Local regression verification after this change: API `109 passed` with all 17 PostgreSQL tests on
  an isolated migrated database, agent `47 passed`, launcher `53 passed`; Ruff format/check, strict
  mypy, Docker/Podman Compose validation, foundation checks, and whitespace validation passed.
- Remote Fedora verification remains incomplete: PostgreSQL became healthy on
  `127.0.0.1:55432`, but the slow-network launcher retry was stopped when the remote host became
  unavailable and cross-machine testing was deferred.

## Data Retention Foundation

Status: implemented and verified. Development deletion remains intentionally unapproved/unapplied.

- Added immutable retention policy version 1 using server-controlled `Event.ingested_at`: 24 hours
  for opt-in resource/network observations, 7 days for `system.status`, and 30 days for known
  process/network transitions. Unknown event types fail closed and are not automatic targets.
- Added aggregate database/type status and dry-run reports without loading raw payloads or secrets.
- Protected direct Candidate/Incident Event evidence and Detection-mediated source Events. Apply
  deletes only expired standalone Detections and Events, in transactions capped at 1,000 Events.
- Added Alembic `0006_event_retention_index` over `(event_type, ingested_at)`.
- Added `aegisx data-status`, `aegisx prune --dry-run`, and confirmed
  `aegisx prune --apply --yes`. Read-only commands do not take the long-running launcher lock;
  apply does. PostgreSQL is stopped only when the maintenance invocation started it.
- Added [the new-user CLI manual](aegisx-cli-manual.md). Retention remains explicit/manual; no
  local-first storage, scheduled deletion, realtime collector, response, AI, or new UI was added.
- Development read-only proof on 2026-09-12 reported a 307,279,539-byte database with 431,488
  Events, 35,241 Detections, 6 Candidates, 3 Incidents, and 8 protected Events. The fixed-time
  dry-run found 409,309 deletable Events and 33,258 standalone Detections; 2 expired Events were
  protected. No apply command or data deletion was run.
- Full verification: API `127 passed` with all PostgreSQL tests enabled, including forced
  Event-delete failure proving the current Detection/Event batch rolls back atomically; agent
  `47 passed`; launcher `59 passed` with isolated state. API, agent, and launcher Ruff format/check
  and strict mypy passed on 56, 16, and 7 source files. Alembic current/heads and
  `0006 -> 0005 -> 0006` round trip passed. Docker Compose and Podman Compose config validation,
  foundation validation, and `git diff --check` passed.
