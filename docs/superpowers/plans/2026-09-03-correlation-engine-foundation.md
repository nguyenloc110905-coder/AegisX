# Correlation Engine Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic process/listener correlation foundation that persists low-confidence evidence candidates without treating correlation as attack detection or allowing correlation failures to discard valid telemetry.

**Architecture:** Pure correlation strategies consume complete Detection/Event evidence and return immutable results through a strategy-indexed engine. A database-aware CorrelationService loads bounded history and persists idempotent Candidates, while TelemetryIngestionService isolates correlation in a nested savepoint after flushing authoritative Event and Detection rows.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, SQLAlchemy asyncio, Alembic, PostgreSQL 17, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-03-correlation-engine-foundation-design.md`

## Global Constraints

- Correlation is an evidence-supported technical relationship, never an attack conclusion or Incident.
- Process identity is exactly `(device_id, pid, started_at)`; PID alone is not permanent identity.
- Default `correlation_window_seconds` is 300 and every strategy receives the configured duration.
- Correlation errors roll back only the nested savepoint; valid Event and Detection evidence must still commit.
- The initial strategy persists at most one Candidate per `(strategy_id, device_id, pid, started_at)` and intentionally drops later per-listener timeline detail.
- Do not implement incidents, AI, notifications, UI, or later detection packs.
- Do not modify the user's existing `compose.yaml` change.

---

### Task 1: Correlation domain types, strategy, registry, engine, and configuration

**Files:**
- Create: `apps/api/src/aegisx_api/correlation/__init__.py`
- Create: `apps/api/src/aegisx_api/correlation/types.py`
- Create: `apps/api/src/aegisx_api/correlation/strategies/base.py`
- Create: `apps/api/src/aegisx_api/correlation/strategies/process_listener_activity.py`
- Create: `apps/api/src/aegisx_api/correlation/registry.py`
- Create: `apps/api/src/aegisx_api/correlation/engine.py`
- Create: `apps/api/src/aegisx_api/correlation/defaults.py`
- Modify: `apps/api/src/aegisx_api/config.py`
- Modify: `apps/api/tests/test_config.py`
- Create: `apps/api/tests/correlation/__init__.py`
- Create: `apps/api/tests/correlation/factories.py`
- Create: `apps/api/tests/correlation/test_process_listener_activity.py`
- Create: `apps/api/tests/correlation/test_engine.py`

**Interfaces:**
- `CorrelationStrategy.evaluate(evidence: Sequence[Detection], window: timedelta) -> tuple[CorrelationResult, ...]`
- `CorrelationRegistry(strategies: Iterable[CorrelationStrategy]).strategies_for(rule_ids: frozenset[str]) -> tuple[CorrelationStrategy, ...]`
- `CorrelationEngine.evaluate(new_detections: Sequence[Detection], evidence: Sequence[Detection], window: timedelta) -> tuple[CorrelationResult, ...]`
- `create_default_correlation_engine() -> CorrelationEngine`
- `Settings.correlation_window_seconds: int`, default 300, bounds 1..86400.

- [ ] **Step 1: Write failing configuration and strategy tests.** Use literal Event/Detection fixtures to prove a valid same-device/same-PID pair produces one low-confidence score-5 result; different devices/PIDs, listener-before-process, missing `started_at`, and out-of-window pairs produce none. Add fixtures with two eligible distinct `started_at` values and expect ambiguity, then add an old PID-reuse process outside the window and expect the current identity to correlate.
- [ ] **Step 2: Run the RED tests.** Run `uv run --project apps/api pytest apps/api/tests/test_config.py apps/api/tests/correlation/test_process_listener_activity.py -q`. Expected failure: missing `aegisx_api.correlation` and missing `correlation_window_seconds`.
- [ ] **Step 3: Implement the minimal strategy contract and semantics.** Define frozen `CorrelationResult(correlation_key, device_id, strategy_id, start_timestamp, end_timestamp, confidence, aggregate_score, detection_ids, event_ids)`. Parse only positive integer PIDs and ISO `started_at`; build eligible process identities with the inclusive window; return no result for zero or multiple identities; select the earliest `(timestamp, UUID)` listener deterministically; deduplicate evidence IDs; compute `min(100, sum(unique detection contributions))`; hash a canonical `strategy_id|device_id|pid|started_at` string with SHA-256.
- [ ] **Step 4: Write failing registry/engine tests.** Prove duplicate strategy IDs are rejected, relevant rule IDs select the strategy without a giant conditional, no relevant new Detection returns no result, and repeated snapshots for one identity collapse to one result/key.
- [ ] **Step 5: Run registry/engine RED tests.** Run `uv run --project apps/api pytest apps/api/tests/correlation/test_engine.py -q`. Expected failure: registry/engine/default composition modules are missing.
- [ ] **Step 6: Implement registry, engine, defaults, and Settings field.** Index strategies by required rule ID, deduplicate selected strategies and results by stable IDs/keys, and configure the first strategy explicitly in `defaults.py`.
- [ ] **Step 7: Run Task 1 GREEN checks.** Run `uv run --project apps/api pytest apps/api/tests/test_config.py apps/api/tests/correlation -q`, then Ruff and mypy over the API. Expected result: all pass.

### Task 2: Candidate persistence and migration

**Files:**
- Create: `apps/api/src/aegisx_api/models/correlation.py`
- Modify: `apps/api/src/aegisx_api/models/device.py`
- Modify: `apps/api/src/aegisx_api/models/event.py`
- Modify: `apps/api/src/aegisx_api/models/detection.py`
- Modify: `apps/api/src/aegisx_api/models/__init__.py`
- Create: `apps/api/alembic/versions/0004_correlation_foundation.py`
- Modify: `apps/api/tests/test_models.py`
- Modify: `apps/api/tests/test_migrations.py`

**Interfaces:**
- `CorrelationCandidate` persists UUID ID, unique 64-character key, Device FK, strategy ID, start/end timestamps, confidence, aggregate score, reason, and creation time.
- `CorrelationCandidate.detections` and `.events` use composite-primary-key association tables with cascading foreign keys.

- [ ] **Step 1: Write failing model and migration tests.** Persist one Candidate with two Detection and two Event relationships; assert reverse relationships and evidence integrity; assert duplicate key and score 101 fail; assert migration head equals `0004_correlation_foundation`.
- [ ] **Step 2: Run Task 2 RED tests.** Run `uv run --project apps/api pytest apps/api/tests/test_models.py apps/api/tests/test_migrations.py -q`. Expected failure: missing correlation model/revision.
- [ ] **Step 3: Implement model and migration.** Create `correlation_candidates`, `correlation_candidate_detections`, and `correlation_candidate_events`; use named PK/FK/check/unique constraints, cascade deletes, and device/strategy/time indexes. Add typed bidirectional SQLAlchemy relationships and model exports.
- [ ] **Step 4: Run Task 2 GREEN checks.** Run the focused tests, Ruff, and mypy. Expected result: all pass.

### Task 3: Correlation service and savepoint-isolated ingestion

**Files:**
- Create: `apps/api/src/aegisx_api/services/correlation.py`
- Modify: `apps/api/src/aegisx_api/services/telemetry_ingestion.py`
- Modify: `apps/api/src/aegisx_api/main.py`
- Modify: `apps/api/tests/test_telemetry_api.py`
- Modify: `apps/api/tests/integration/test_postgres_ingestion.py`

**Interfaces:**
- `CorrelationService(engine: CorrelationEngine).correlate(session: AsyncSession, device_id: UUID, new_detections: Sequence[Detection], window: timedelta) -> int` adds only absent Candidates and returns their count without committing.
- `TelemetryIngestionService(detection_engine, correlation_service, correlation_window)` flushes authoritative rows, calls correlation inside `session.begin_nested()`, catches/logs correlation-only failures, then commits the outer transaction.

- [ ] **Step 1: Write failing ingestion tests.** Submit a process-start and matching listener and assert one Candidate plus relational evidence; submit another listener snapshot and assert Candidate/evidence/score remain unchanged; retry duplicate Events and assert idempotency; inject a CorrelationService that raises and assert HTTP 202 plus persisted Event/Detection rows and zero Candidate rows.
- [ ] **Step 2: Run Task 3 RED tests.** Run `uv run --project apps/api pytest apps/api/tests/test_telemetry_api.py -q`. Expected failures: Candidate persistence and failure isolation are not integrated.
- [ ] **Step 3: Implement CorrelationService.** Query only same-device `PROCESS_STARTED`/`LISTENER_OBSERVED` Detections in the configured bounded range with source Events eagerly loaded, combine them with new flushed Detections, evaluate relevant strategies, query existing keys, and add new Candidate association rows without committing.
- [ ] **Step 4: Integrate the savepoint boundary.** Collect new Detection objects during mapping, `await session.flush()`, enter `async with session.begin_nested()`, call correlation, catch correlation exceptions outside the savepoint, emit a structured error containing device and triggering Event IDs, and always attempt the authoritative outer commit. Do not catch Event/Detection flush or outer-commit failures.
- [ ] **Step 5: Extend PostgreSQL integration.** Submit matching process/listener evidence, verify Candidate fields and both association tables, submit a repeated listener snapshot, verify one Candidate and unchanged evidence/score, then clean up through Device cascade.
- [ ] **Step 6: Run Task 3 GREEN checks.** Run focused SQLite API tests and the PostgreSQL integration test with `AEGISX_TEST_POSTGRES_URL=postgresql+asyncpg://aegisx:aegisx_dev_only@127.0.0.1:5432/aegisx`; run Ruff and mypy. Expected result: all pass.

### Task 4: Documentation and final verification

**Files:**
- Create: `docs/correlation-engine.md`
- Modify: `docs/detection-engine.md`
- Modify: `docs/implementation-map.md`
- Modify: `docs/progress.md`

- [ ] **Step 1: Document current behavior.** Record the exact Event/Detection/Correlation/Incident boundary, actual keys, eligible-set ambiguity rule, configurable inclusive window, savepoint failure semantics, persisted schema/evidence, one-Candidate limit, score semantics, lost timeline detail, and exclusions.
- [ ] **Step 2: Search for stale claims.** Run `rg -n "correlation.*not implemented|Correlation Engine.*not implemented|0003_detection_foundation|Event.*Detection" docs README.md` and update only current-state documentation; preserve historical milestone evidence as historical.
- [ ] **Step 3: Run full verification.** Run complete API tests with PostgreSQL integration enabled, complete agent tests, Ruff format/check, strict mypy, Alembic upgrade/current/heads, and `git diff --check`. All commands must exit zero.
- [ ] **Step 4: Commit and push.** Stage only Milestone 5A files, explicitly exclude the user's modified `compose.yaml`, commit the verified implementation, and push `main` without force.
