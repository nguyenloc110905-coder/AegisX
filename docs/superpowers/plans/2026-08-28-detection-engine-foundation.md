# Detection Engine Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and persist deterministic, explainable detections for verified process starts and observed listeners without adding correlation or incidents.

**Architecture:** Pure rule objects are indexed by a registry and evaluated by a rule-agnostic engine. A telemetry ingestion service maps validated envelopes, evaluates new Events, persists Event and Detection rows in one transaction, and leaves the FastAPI route as an HTTP boundary.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy asyncio, Alembic, PostgreSQL, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-28-detection-engine-foundation-design.md`

## Global Constraints

- Do not implement correlation, incidents, AI, notifications, UI, or later detection packs.
- Risk scores are deterministic heuristic contributions, never malware probabilities.
- `network.listener_observed` remains snapshot evidence and must not be described as newly opened.
- `HIGH_RESOURCE_USAGE` is deferred because one current sample is insufficient evidence.
- Use TDD and observe each new behavior fail before production implementation.

---

### Task 1: Rule contract, registry, engine, scoring, and first rules

**Files:**
- Create: `apps/api/src/aegisx_api/detection/types.py`
- Create: `apps/api/src/aegisx_api/detection/rules/base.py`
- Create: `apps/api/src/aegisx_api/detection/rules/process_started.py`
- Create: `apps/api/src/aegisx_api/detection/rules/listener_observed.py`
- Create: `apps/api/src/aegisx_api/detection/registry.py`
- Create: `apps/api/src/aegisx_api/detection/engine.py`
- Create: `apps/api/src/aegisx_api/detection/scoring.py`
- Create: `apps/api/src/aegisx_api/detection/defaults.py`
- Test: `apps/api/tests/detection/test_rules.py`
- Test: `apps/api/tests/detection/test_engine.py`
- Test: `apps/api/tests/detection/test_scoring.py`

**Interfaces:**
- `DetectionRule.evaluate(event: Event) -> RuleMatch | None`
- `RuleRegistry(rules: Iterable[DetectionRule]).rules_for(event_type: str) -> tuple[DetectionRule, ...]`
- `DetectionEngine.evaluate(event: Event) -> list[DetectionResult]`
- `calculate_risk_score(results: Iterable[DetectionResult]) -> int`
- `create_default_engine() -> DetectionEngine`

- [ ] Write tests proving process/listener matching, irrelevant and malformed data handling, neutral reasons, exact severity/contribution, source evidence UUID, benign Python listener behavior, registry duplicate rejection/indexing, engine zero/multiple results, and score clamp/negative rejection.
- [ ] Run `uv run --project apps/api pytest apps/api/tests/detection -q` and confirm collection/import failures are caused by missing detection modules.
- [ ] Implement frozen result types, protocol, two pure rules, indexed registry, rule-agnostic engine, scoring function, and default composition.
- [ ] Run the detection tests and confirm they pass.

### Task 2: Detection model and Alembic migration

**Files:**
- Create: `apps/api/src/aegisx_api/models/detection.py`
- Modify: `apps/api/src/aegisx_api/models/device.py`
- Modify: `apps/api/src/aegisx_api/models/event.py`
- Modify: `apps/api/src/aegisx_api/models/__init__.py`
- Create: `apps/api/alembic/versions/0003_detection_foundation.py`
- Modify: `apps/api/tests/test_models.py`
- Modify: `apps/api/tests/test_migrations.py`

**Interfaces:**
- `Detection` stores `device_id`, `source_event_id`, `rule_id`, `timestamp`, `severity`, `score_contribution`, `reason`, and `evidence_event_ids`.
- Device/Event expose cascading `detections` relationships.

- [ ] Add failing model tests for persistence, relationships, evidence IDs, score bounds, and cascade behavior; add a failing migration-head assertion for `0003_detection_foundation`.
- [ ] Run focused model/migration tests and confirm expected failures.
- [ ] Implement the model, relationships, exports, indexes, constraints, upgrade, and downgrade.
- [ ] Run focused tests and confirm they pass.

### Task 3: Transactional telemetry/detection ingestion service

**Files:**
- Create: `apps/api/src/aegisx_api/services/telemetry_ingestion.py`
- Modify: `apps/api/src/aegisx_api/api/telemetry.py`
- Modify: `apps/api/src/aegisx_api/main.py`
- Modify: `apps/api/tests/test_telemetry_api.py`
- Modify: `apps/api/tests/integration/test_postgres_ingestion.py`

**Interfaces:**
- `TelemetryIngestionService(engine: DetectionEngine).ingest(session, device, envelopes) -> EventBatchResponse`
- `app.state.detection_engine` is composed once by `create_app()`.

- [ ] Add failing API tests proving a new relevant Event persists its Detection, an irrelevant Event persists none, duplicate ingestion does not duplicate Detection, and the route delegates security work outside the handler through real observable persistence.
- [ ] Run focused telemetry tests and confirm expected failures.
- [ ] Extract mapping/deduplication/transaction code into the service, evaluate only new Events, map results to Detection rows, and make the route call the service.
- [ ] Extend the PostgreSQL integration test to verify the Detection FK, rule, evidence UUID, score, and cleanup.
- [ ] Run focused SQLite and PostgreSQL tests and confirm they pass.

### Task 4: Documentation and complete verification

**Files:**
- Modify: `docs/detection-engine.md`
- Modify: `docs/event-model.md`
- Modify: `docs/implementation-map.md`
- Modify: `docs/progress.md`

- [ ] Document exact pipeline, rule contract, registry, implemented/deferred rules, heuristic scoring, persistence, evidence linkage, transaction behavior, and exclusions.
- [ ] Run API and agent tests, Ruff format/check, mypy, PostgreSQL integration, Alembic upgrade/current/heads, and `git diff --check`.
- [ ] Commit and push only after every final verification command exits successfully.
