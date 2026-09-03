# Milestone 5B — Telemetry Fidelity & Operational Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evidence-backed process and network transitions, keep SQLite outbox work off the async event loop, and make correlation failures operationally diagnosable without changing correlation semantics.

**Architecture:** Process and network collectors compare two complete consecutive snapshots against private atomic JSON baselines. Failed, truncated, inaccessible, or ambiguous observations retain the last trustworthy identity instead of inventing a transition. The runner accesses the existing synchronous SQLite outbox through one serialized async adapter, while telemetry ingestion records correlation outcomes only after authoritative Event/Detection persistence commits.

**Tech Stack:** Python 3.12, psutil, Pydantic, asyncio, SQLite, FastAPI, SQLAlchemy async, structlog, PostgreSQL 17, pytest, Ruff, mypy, Alembic, Docker Compose.

**Spec:** User-approved Milestone 5B request in the 2026-09-03 conversation; existing semantics are documented in `docs/event-model.md`, `docs/agent.md`, and `docs/correlation-engine.md`.

## Global Constraints

- Do not implement Incident, AI Investigator, Web UI, notifications, advanced attack detection packs, DNS, Wi-Fi, or packaging/onboarding UX.
- Do not change Milestone 5A correlation matching, identity, scoring, idempotency, or persistence semantics.
- A transition event is emitted only from two consecutive complete snapshots; a lookup failure is not transition evidence.
- Preserve Event and Detection rows when correlation fails.
- Inspect and preserve unrelated user changes before every commit; push `main` only after full verification.

---

### Task 1: Repair and verify the development Compose configuration

**Files:**
- Modify: `compose.yaml`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: `.env.example` PostgreSQL development defaults.
- Produces: a valid `services.postgres.volumes` YAML list with the named data volume and read-only SELinux-labelled initialization mount.

- [ ] Restore `volumes:` and `- postgres_data:/var/lib/postgresql/data` without touching other Compose settings.
- [ ] Run `docker compose --env-file .env.example config --quiet` and inspect the rendered PostgreSQL volumes.
- [ ] Run PostgreSQL with Docker Compose, wait for health, then execute `pg_isready` and `SELECT 1`.
- [ ] Update the Milestone 5B Task 1 entry in `docs/progress.md` with exact results.
- [ ] Run `git diff --check`, review the staged diff, and commit as `fix: repair PostgreSQL Compose volumes`.

### Task 2: Add truthful process exit transitions

**Files:**
- Modify: `apps/agent/tests/test_process_collector.py`
- Modify: `apps/agent/src/aegisx_agent/collectors/process.py`
- Modify: `apps/api/tests/test_telemetry_api.py`
- Modify: `apps/api/src/aegisx_api/schemas/event.py`
- Modify: `docs/event-model.md`
- Modify: `docs/agent.md`
- Modify: `docs/implementation-map.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: psutil process snapshot records and persisted `(pid, create_time)` incarnation identity.
- Produces: schema-version-1 `process.exited` with positive `pid` and `started_at`; a versioned atomic process baseline retaining enough identity data to describe a prior incarnation.

- [ ] Write failing collector tests for first baseline, unchanged process, one confirmed absence, inaccessible lookup retention, PID reuse, and same-PID restart producing old exit plus new start.
- [ ] Run the focused tests and confirm failures are caused by missing `process.exited` behavior.
- [ ] Replace truncate-in-place state writes with a private temporary file, `fsync`, permission `0600`, and `os.replace`; retain backward reading of version-1 keys.
- [ ] Suppress all transitions and baseline replacement when process enumeration is incomplete or raises. Continue scanning identities after the output cap so the cap cannot manufacture absence; any per-process lookup failure makes that snapshot ineligible for lifecycle comparison.
- [ ] Emit `process.exited` only for a prior incarnation absent from a complete current snapshot, and emit both exit/start for trustworthy PID reuse.
- [ ] Add failing then passing API validation tests for the `process.exited` payload.
- [ ] Run focused agent/API tests plus Ruff and mypy for changed packages.
- [ ] Document exact semantics and limitations, update progress, review diff, and commit as `feat: add truthful process exit telemetry`.

### Task 3: Add evidence-backed network transitions

**Files:**
- Modify: `apps/agent/tests/test_network_collector.py`
- Modify: `apps/agent/src/aegisx_agent/collectors/network.py`
- Modify: `apps/agent/src/aegisx_agent/runner.py`
- Modify: `apps/api/tests/test_telemetry_api.py`
- Modify: `apps/api/src/aegisx_api/schemas/event.py`
- Modify: `docs/event-model.md`
- Modify: `docs/agent.md`
- Modify: `docs/implementation-map.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: complete consecutive `psutil.net_connections(kind="inet")` snapshots.
- Produces: existing observed events plus `network.listener_opened`, `network.listener_closed`, `network.connection_opened`, and `network.connection_closed` when endpoint presence changes.

- [ ] Write failing tests for baseline-only observations, repeated snapshots, opened/closed listeners, opened/closed connections, duplicate canonical identities, malformed records, collection errors, and restart persistence.
- [ ] Run focused tests and verify RED for absent transition behavior.
- [ ] Canonicalize listener identity as `(protocol, local_ip, local_port)` and connection identity as `(protocol, local_ip, local_port, remote_ip, remote_port)`; PID and state remain attributes, not identity.
- [ ] Persist a versioned atomic network baseline. Suppress transitions and baseline replacement for capped/malformed snapshots; suppress only duplicated identities that cannot represent a unique socket while retaining their observed events.
- [ ] Emit observed events for every current valid record and transition events only from two trustworthy consecutive snapshots; closed events reuse the last trustworthy prior attributes.
- [ ] Pass `network-state.json` from the runner, add API union models for all four transition event names, and verify focused API tests.
- [ ] Run focused agent/API tests plus Ruff and mypy for changed packages.
- [ ] Document identities, semantics, and missing process-create-time/OS visibility limitations; update progress and commit as `feat: add truthful network transition telemetry`.

### Task 4: Keep SQLite outbox I/O off the event loop

**Files:**
- Modify: `apps/agent/tests/test_outbox.py`
- Modify: `apps/agent/tests/test_runner.py`
- Modify: `apps/agent/src/aegisx_agent/outbox.py`
- Modify: `apps/agent/src/aegisx_agent/runner.py`
- Modify: `docs/agent.md`
- Modify: `docs/implementation-map.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: existing synchronous ordered `Outbox` operations.
- Produces: `AsyncOutbox` with serialized async `enqueue`, `peek`, `acknowledge`, `quarantine`, `count`, and `close` methods backed by `asyncio.to_thread`.

- [ ] Write failing async tests proving the runner awaits outbox operations and concurrent adapter calls preserve sequence/order.
- [ ] Run focused tests and verify RED for the missing async adapter.
- [ ] Allow the private SQLite connection to cross worker threads, then guard every adapter call with one `asyncio.Lock` so no connection operation overlaps.
- [ ] Convert runner outbox interactions and recursive quarantine delivery to awaited adapter calls without changing batching, retry, quarantine, eviction, or UUID idempotency.
- [ ] Run all outbox/runner tests plus the full agent suite, Ruff, and strict mypy.
- [ ] Document the concurrency boundary, update progress, review diff, and commit as `perf: offload agent outbox I/O`.

### Task 5: Add truthful correlation operational logging

**Files:**
- Modify: `apps/api/tests/test_telemetry_api.py`
- Modify: `apps/api/src/aegisx_api/correlation/engine.py`
- Modify: `apps/api/src/aegisx_api/services/telemetry_ingestion.py`
- Modify: `docs/correlation-engine.md`
- Modify: `docs/implementation-map.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: relevant strategy IDs selected from newly persisted Detection rule IDs and the unchanged `CorrelationService.correlate(...) -> int` result.
- Produces: bounded structured logs containing strategy IDs, device ID, outcome, failure category, and authoritative evidence commit status, without event payloads or credentials.

- [ ] Write failing ingestion tests for candidate-created, no-candidate, correlation failure after successful evidence commit, and outer commit failure not claiming retained evidence.
- [ ] Run focused tests and verify RED for missing structured fields/timing.
- [ ] Expose selected strategy IDs as a read-only engine method and use it only for observability; leave evaluation and persistence unchanged.
- [ ] Capture a correlation failure inside the existing savepoint, commit Event/Detection evidence, then log `evidence_committed=true`; log successful outcomes as `candidate_created` or `no_candidate`.
- [ ] Include exception class as `failure_category`; never log token, command line, raw data, metadata, or broad accepted-event UUID lists.
- [ ] Run focused API tests, PostgreSQL ingestion integration tests, Ruff, and strict mypy.
- [ ] Document the logging contract, update progress, review diff, and commit as `chore: add correlation outcome logging`.

### Task 6: Final documentation, verification, and push

**Files:**
- Modify: `docs/event-model.md`
- Modify: `docs/agent.md`
- Modify: `docs/correlation-engine.md`
- Modify: `docs/implementation-map.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: all verified Milestone 5B behavior.
- Produces: an evidence-backed milestone record and synchronized `origin/main`.

- [ ] Review all required docs for exact current behavior and remove stale snapshot-only claims.
- [ ] Run API tests and real PostgreSQL integration tests.
- [ ] Run agent tests.
- [ ] Run Ruff format checks and lint checks for both projects.
- [ ] Run strict mypy for both projects.
- [ ] Run Alembic `current`, `heads`, upgrade/downgrade/upgrade verification against PostgreSQL; confirm no schema migration is required by this milestone.
- [ ] Run Docker Compose config validation, PostgreSQL readiness/query checks, `git diff --check`, and `git status --short --branch`.
- [ ] Update `docs/progress.md` with exact command outputs/counts and commit as `docs: verify Milestone 5B hardening`.
- [ ] Review the full commit range for scope violations, ensure Incident/AI/UI/notifications/detection packs are absent, then push `main` and verify local/remote commit equality.
