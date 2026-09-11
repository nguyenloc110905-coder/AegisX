# Data Retention Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe PostgreSQL volume reporting and explicit batched pruning that removes expired low-value Event/Detection chains while preserving every Candidate/Incident evidence reference.

**Architecture:** A versioned pure policy feeds a PostgreSQL maintenance service. An API-package CLI renders bounded aggregate output, while the top-level launcher owns Compose lifecycle and invokes it without embedding SQL. Pruning is manual, dry-run-first, batch-transactional, and fail-closed for unknown event types.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, PostgreSQL 17, Alembic, argparse, pytest, Ruff, strict mypy.

**Spec:** `docs/superpowers/specs/2026-09-11-data-retention-foundation-design.md`

## Global Constraints

- Use `events.ingested_at`, never agent-controlled `events.timestamp`, for retention age.
- Policy version is `1`: 24 hours for metrics/snapshots, 7 days for `system.status`, 30 days for known transitions.
- Unknown Event types are not automatic prune targets.
- Never delete Candidate, Incident, status transition, or their direct/indirect evidence.
- Apply processes at most 1,000 Events per committed transaction.
- Refuse `prune --apply` unless `--yes` is present.
- Never run `VACUUM FULL` or modify agent identity, outbox, credentials, or baselines.
- Do not add local-first storage, automatic pruning, realtime eBPF, AI, notifications, response, or new UI.

---

### Task 1: Versioned Policy and Query Index

**Files:**
- Create: `apps/api/src/aegisx_api/maintenance/__init__.py`
- Create: `apps/api/src/aegisx_api/maintenance/retention_policy.py`
- Create: `apps/api/tests/maintenance/__init__.py`
- Create: `apps/api/tests/maintenance/test_retention_policy.py`
- Create: `apps/api/alembic/versions/0006_event_retention_index.py`
- Modify: `apps/api/tests/test_migrations.py`

**Interfaces:**
- Produces `RETENTION_POLICY_VERSION: Final[int] = 1`.
- Produces frozen `RetentionRule(event_type: str, retention: timedelta)`.
- Produces deterministic `RETENTION_RULES: Final[tuple[RetentionRule, ...]]`.
- Produces `cutoff_for(rule, evaluation_time) -> datetime` requiring timezone-aware input.

- [ ] **Step 1: Write failing policy tests**

Assert the exact ten event types and TTLs from the spec, policy version 1, UTC cutoff math, rejection of naive timestamps, and rejection of non-positive TTLs.

- [ ] **Step 2: Verify RED**

Run `uv run --project apps/api pytest -q apps/api/tests/maintenance/test_retention_policy.py` and require import failure for the absent module.

- [ ] **Step 3: Implement minimal immutable policy**

Implement only the interfaces above. Do not add environment overrides.

- [ ] **Step 4: Write migration test before migration**

Require head `0006_event_retention_index` and index `ix_events_event_type_ingested_at` over exactly `(event_type, ingested_at)`. Run the migration test and require RED, then add exact upgrade/drop-index downgrade.

- [ ] **Step 5: Verify and commit**

Run focused tests, Ruff, and strict API mypy. Commit as `feat(retention): define versioned event expiry policy`.

### Task 2: Status and Dry-run Reports

**Files:**
- Create: `apps/api/src/aegisx_api/maintenance/types.py`
- Create: `apps/api/src/aegisx_api/maintenance/retention_service.py`
- Create: `apps/api/tests/maintenance/test_retention_service.py`
- Create: `apps/api/tests/integration/test_postgres_retention.py`

**Interfaces:**
- Frozen values: `EventTypeStats`, `DataStatus`, `PruneRuleReport`, `PruneReport`.
- `RetentionService(session_factory)`.
- `async data_status() -> DataStatus`.
- `async dry_run(evaluation_time: datetime) -> PruneReport`.

- [ ] **Step 1: Write failing report tests**

Test non-negative counts, timezone-aware timestamps, deterministic sorting, totals, and that unknown types appear in status but never prune rules.

- [ ] **Step 2: Verify RED and implement read-only queries**

Use aggregate SQL only: counts, oldest/newest ingestion, `pg_database_size`, and the four protection predicates. Never load Event payloads.

- [ ] **Step 3: Write PostgreSQL boundary tests**

Insert rows one microsecond before, exactly at, and one microsecond after each cutoff. Add direct Candidate/Incident Event references plus indirect Detection references. Assert inclusive expiry and zero mutations.

- [ ] **Step 4: Verify and commit**

Migrate an isolated PostgreSQL database, run focused integration tests, Ruff, and mypy. Commit as `feat(retention): report database volume and prune eligibility`.

### Task 3: Transactional Batched Pruning

**Files:**
- Modify: `apps/api/src/aegisx_api/maintenance/types.py`
- Modify: `apps/api/src/aegisx_api/maintenance/retention_service.py`
- Modify: `apps/api/tests/maintenance/test_retention_service.py`
- Modify: `apps/api/tests/integration/test_postgres_retention.py`

**Interfaces:**
- `PruneResult(policy_version, evaluation_time, deleted_events, deleted_detections, completed)`.
- `async prune(evaluation_time: datetime, batch_size: int = 1000) -> PruneResult`.
- `RetentionPruneError` exposes committed counts and exception class category without SQL text.

- [ ] **Step 1: Write failing apply tests**

Require expired unprotected rows and their standalone Detections to disappear, recent/unknown/protected rows to survive, and Candidate/Incident/status-transition counts to remain unchanged. Apply twice; the second deletes zero.

- [ ] **Step 2: Verify RED**

Run the retention integration file and require failure because `prune` is absent.

- [ ] **Step 3: Implement one batch**

Select IDs ordered by `(ingested_at, id)`, limited to the validated batch size, with `FOR UPDATE SKIP LOCKED` and all four `NOT EXISTS` protection checks. Delete Detections before Events inside one transaction.

- [ ] **Step 4: Implement policy loop and failure semantics**

Commit each batch. On failure, roll back only that batch, preserve prior committed counts, emit no payload/SQL, and make retry safe.

- [ ] **Step 5: Add forced-failure test and commit**

Force failure between Detection and Event deletion and prove current-batch rollback. Run full API tests with PostgreSQL, Ruff, and mypy. Commit as `feat(retention): prune expired evidence in safe batches`.

### Task 4: Maintenance CLI and Launcher Integration

**Files:**
- Create: `apps/api/src/aegisx_api/maintenance/cli.py`
- Create: `apps/api/tests/maintenance/test_cli.py`
- Modify: `apps/api/pyproject.toml`
- Modify: `tools/launcher/src/aegisx_launcher/cli.py`
- Modify: `tools/launcher/src/aegisx_launcher/runtime.py`
- Modify: `tools/launcher/tests/test_project.py`
- Modify: `tools/launcher/tests/test_runtime.py`

**Interfaces:**
- API entry point `aegisx-maintenance = "aegisx_api.maintenance.cli:main"`.
- User commands `data-status`, `prune --dry-run`, and `prune --apply --yes`.
- Runtime methods `data_status() -> int` and `prune(apply: bool, confirmed: bool) -> int`.

- [ ] **Step 1: Write failing maintenance CLI tests**

With a fake service, prove status/dry-run are read-only, unsafe apply returns 2 without service mutation, confirmed apply runs once, and output excludes payload/token fixtures.

- [ ] **Step 2: Implement maintenance CLI**

Use argparse, asyncio, existing Settings/session factory, stable plain-text output, bounded errors, and no SQL in the CLI module.

- [ ] **Step 3: Write failing launcher tests**

Cover exact argv, parsing, provider fallback, PostgreSQL ownership preservation/cleanup, and apply confirmation. Read-only commands do not take the long-running launcher lock; apply does.

- [ ] **Step 4: Implement smallest lifecycle refactor**

Share only provider/start/sync/migrate/cleanup behavior required by run and maintenance. Preserve every existing launcher command and test.

- [ ] **Step 5: Verify and commit**

Run complete API and launcher suites, Ruff, and strict mypy. Commit as `feat(cli): expose safe data retention commands`.

### Task 5: CLI Manual, Dry-run, and Full Verification

**Files:**
- Create: `docs/aegisx-cli-manual.md`
- Modify: `README.md`
- Modify: `docs/development.md`
- Modify: `docs/implementation-map.md`
- Modify: `docs/progress.md`
- Modify: `scripts/check-foundation.sh`

**Interfaces:**
- Produces the canonical new-user CLI manual requested by the user.
- Foundation validation requires the manual and all supported command names.

- [ ] **Step 1: Write failing foundation check**

Require the manual plus literal `aegisx run`, `aegisx doctor`, `aegisx data-status`, `aegisx prune --dry-run`, and `aegisx prune --apply --yes`. Run the check and require RED.

- [ ] **Step 2: Write the manual**

Document installation, first run, console keys, commands, storage locations, pruning safety, backup warning, provider/port/PATH/slow-network troubleshooting, polling limitations, and the future packaged endpoint boundary. Examples contain no credentials.

- [ ] **Step 3: Run development read-only proof**

Run `aegisx data-status` and `aegisx prune --dry-run`; record exact counts. Do not apply deletion to user data until the user separately approves the displayed dry-run.

- [ ] **Step 4: Run full verification**

Run API tests with all PostgreSQL integration cases, agent tests, launcher tests with isolated state, Ruff format/check, strict mypy, Alembic upgrade/current/heads plus downgrade/upgrade, Docker and Podman Compose validation, foundation validation, and `git diff --check`.

- [ ] **Step 5: Commit and push**

Confirm no scope expansion. Commit as `docs: publish AegisX CLI data maintenance manual`, verify clean status, and push `main` only after every check passes.
