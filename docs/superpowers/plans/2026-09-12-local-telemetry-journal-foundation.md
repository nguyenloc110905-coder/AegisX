# Local Telemetry Journal Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every agent-generated Event in a bounded, verifiable endpoint SQLite journal while preserving the current retry/delivery contract and server pipeline.

**Architecture:** Replace the delivery-only SQLite schema behind the current outbox path with a versioned `LocalTelemetryStore`. Journal append and delivery state share one SQLite transaction; a compatibility adapter keeps the existing runner interface while the new local maintenance CLI exposes status, verification, and safe pruning. Server admission remains unchanged in this milestone.

**Tech Stack:** Python 3.12, stdlib SQLite/WAL and hashlib, asyncio thread offloading, Pydantic Settings, argparse, pytest, Ruff, strict mypy.

**Spec:** `docs/superpowers/specs/2026-09-12-local-telemetry-journal-foundation-design.md`

## Global Constraints

- Store all `NormalizedEvent` values emitted by current collectors before any network call.
- Keep `outbox.sqlite3` as the physical path and upgrade it in-place to `PRAGMA user_version = 2`.
- Preserve oldest-first delivery, server UUID idempotency, retry, quarantine, and cancellation safety.
- Never silently evict pending, quarantined, unclassified, or not-yet-expired evidence.
- Use stable global sequence plus per-event SHA-256 checksum; do not claim tamper-proof storage.
- Default logical payload quota is 256 MiB; configuration is bounded from 64 MiB through 10 GiB.
- Local maintenance commands must not require PostgreSQL or a Compose provider.
- Do not change server sync selection, API schemas, Detection, CorrelationCandidate, Incident, Decision, Response, or collector semantics.
- Do not implement eBPF, encryption, TPM, signed checkpoints, scheduled pruning, AI, notifications, or web/desktop UI.
- Preserve the unrelated untracked `docs/cau-hoi-trien-khai-thuc-te.md` file.

---

### Task 1: Pure Local Policy, Canonical Payload, and Checksum Types

**Files:**
- Create: `apps/agent/src/aegisx_agent/local_policy.py`
- Create: `apps/agent/src/aegisx_agent/local_types.py`
- Create: `apps/agent/tests/test_local_policy.py`
- Modify: `apps/agent/src/aegisx_agent/config.py`
- Modify: `apps/agent/tests/test_config.py`

**Interfaces:**
- Produces `LOCAL_POLICY_VERSION: Final[int] = 1`.
- Produces `EventPriority(StrEnum)` with `BULK`, `OPERATIONAL`, `SECURITY`, `UNCLASSIFIED`.
- Produces `DeliveryState(StrEnum)` with `PENDING`, `ACKED`, `QUARANTINED`.
- Produces `classify_event(event_type: str) -> EventPriority` and `retention_for(priority) -> timedelta | None`.
- Produces `canonical_event_json(event: NormalizedEvent) -> str` using sorted compact JSON.
- Produces `calculate_payload_hash(canonical_payload: str) -> str`.
- Adds `AgentSettings.local_telemetry_max_bytes: int` from `AEGISX_LOCAL_TELEMETRY_MAX_BYTES`, default `268_435_456`, bounds `67_108_864..10_737_418_240`.

- [ ] **Step 1: Write policy and configuration tests first**

Add exact mapping, retention, canonicalization, checksum sensitivity, timezone, and configuration boundary cases:

```python
def test_local_policy_classifies_only_known_event_types() -> None:
    assert classify_event("process.resource_usage") is EventPriority.BULK
    assert classify_event("system.status") is EventPriority.OPERATIONAL
    assert classify_event("process.started") is EventPriority.SECURITY
    assert classify_event("future.event") is EventPriority.UNCLASSIFIED
    assert retention_for(EventPriority.BULK) == timedelta(hours=24)
    assert retention_for(EventPriority.UNCLASSIFIED) is None


def test_local_quota_defaults_to_256_mib() -> None:
    settings = AgentSettings(_env_file=None)
    assert settings.local_telemetry_max_bytes == 256 * 1024 * 1024
```

- [ ] **Step 2: Run RED**

Run:

```bash
uv run --project apps/agent pytest -q \
  apps/agent/tests/test_local_policy.py \
  apps/agent/tests/test_config.py
```

Expected: collection fails because `aegisx_agent.local_policy` and the new setting do not exist.

- [ ] **Step 3: Implement the pure policy and types**

Use explicit code-owned mappings, never substring inference:

```python
class EventPriority(StrEnum):
    BULK = "BULK"
    OPERATIONAL = "OPERATIONAL"
    SECURITY = "SECURITY"
    UNCLASSIFIED = "UNCLASSIFIED"


EVENT_PRIORITIES: Final = {
    "process.resource_usage": EventPriority.BULK,
    "network.listener_observed": EventPriority.BULK,
    "network.connection_observed": EventPriority.BULK,
    "system.status": EventPriority.OPERATIONAL,
    "process.started": EventPriority.SECURITY,
    "process.exited": EventPriority.SECURITY,
    "network.listener_opened": EventPriority.SECURITY,
    "network.listener_closed": EventPriority.SECURITY,
    "network.connection_opened": EventPriority.SECURITY,
    "network.connection_closed": EventPriority.SECURITY,
}
```

Canonical JSON must derive from `event.model_dump(mode="json")`, then use:

```python
json.dumps(
    event.model_dump(mode="json"),
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
)
```

- [ ] **Step 4: Run GREEN and quality checks**

```bash
uv run --project apps/agent pytest -q \
  apps/agent/tests/test_local_policy.py \
  apps/agent/tests/test_config.py
uv run --project apps/agent ruff format apps/agent/src apps/agent/tests
uv run --project apps/agent ruff check apps/agent/src apps/agent/tests
uv run --project apps/agent mypy --strict apps/agent/src
```

- [ ] **Step 5: Commit Task 1**

```bash
git add apps/agent/src/aegisx_agent/local_policy.py \
  apps/agent/src/aegisx_agent/local_types.py \
  apps/agent/src/aegisx_agent/config.py \
  apps/agent/tests/test_local_policy.py \
  apps/agent/tests/test_config.py
git commit -m "feat(agent): define local telemetry storage policy"
```

### Task 2: Secure SQLite v2 Schema and Legacy Migration

**Files:**
- Create: `apps/agent/src/aegisx_agent/local_store.py`
- Create: `apps/agent/tests/test_local_store.py`
- Modify: `apps/agent/src/aegisx_agent/outbox.py`
- Modify: `apps/agent/tests/test_outbox.py`

**Interfaces:**
- Consumes Task 1 priorities, delivery states, canonical JSON, and record hashing.
- Produces exceptions `LocalStoreError`, `LocalStoreIntegrityError`, `LocalStoreCapacityError`, `LocalStoreMigrationError`.
- Produces synchronous `LocalTelemetryStore(path: Path, max_events: int, max_payload_bytes: int, clock: Callable[[], datetime] = utc_now)`.
- Produces `enqueue(events: list[NormalizedEvent]) -> int`, preserving the old return type with successful value `0`; no eviction is permitted.
- Produces `peek(limit)`, `acknowledge(ids)`, `quarantine(ids, reason)`, `count()`, `quarantine_count()`, `quarantine_reasons()`, and `close()`.
- `max_events` bounds the combined `PENDING` plus `QUARANTINED` delivery backlog; `ACKED` journal
  history is controlled by byte quota/retention instead. Capacity refusal never deletes an older row.
- Keeps `Outbox` as a compatibility alias/wrapper and does not add new logic to it.

- [ ] **Step 1: Write fresh-database and filesystem safety tests**

Tests create a real SQLite file and assert schema version, modes, foreign-key/WAL/synchronous configuration, stable global sequence, correct payload checksum, same-payload UUID idempotency, conflicting-payload rejection, symlink refusal, non-regular-file refusal, and future-schema refusal:

```python
def test_enqueue_persists_pending_event_with_sequence_and_checksum(tmp_path: Path) -> None:
    store = LocalTelemetryStore(
        tmp_path / "outbox.sqlite3",
        max_events=100,
        max_payload_bytes=64 * 1024 * 1024,
        clock=lambda: FIXED_TIME,
    )
    store.enqueue([event(EVENT_ID, "system.status")])

    assert store.count() == 1
    assert store.peek(10)[0].id == EVENT_ID
    store.close()

    with sqlite3.connect(tmp_path / "outbox.sqlite3") as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert connection.execute(
            "SELECT delivery_state FROM local_events WHERE event_id = ?", (EVENT_ID,)
        ).fetchone() == ("PENDING",)
```

- [ ] **Step 2: Run RED**

```bash
uv run --project apps/agent pytest -q apps/agent/tests/test_local_store.py
```

Expected: import failure because `LocalTelemetryStore` does not exist.

- [ ] **Step 3: Implement schema creation and append transaction**

Open with explicit safety checks, set `busy_timeout`, `foreign_keys=ON`, `journal_mode=WAL`,
`synchronous=FULL`, run `quick_check`, and create the exact v2 tables/indexes from the spec.
Serialize the transaction with `BEGIN IMMEDIATE`; assign the global sequence, calculate SHA-256 over
canonical payload, insert the journal row and set `PENDING` atomically.

Duplicate handling is exact:

```python
existing = connection.execute(
    "SELECT payload FROM local_events WHERE event_id = ?", (event.id,)
).fetchone()
if existing is not None:
    if existing[0] != canonical_payload:
        raise LocalStoreIntegrityError("event UUID maps to conflicting immutable payload")
    continue
```

- [ ] **Step 4: Write legacy migration tests before migration code**

Build real schema-v0 databases with the old `pending_events` and `quarantined_events` definitions.
Assert pending/quarantined UUIDs and payloads survive, migration rerun is idempotent, malformed JSON
rolls back without changing `user_version`, and old ACKED rows are not invented.

- [ ] **Step 5: Run migration RED**

```bash
uv run --project apps/agent pytest -q \
  apps/agent/tests/test_local_store.py -k 'legacy or migration'
```

Expected: schema-open or assertion failure because v0 import is not implemented.

- [ ] **Step 6: Implement one-transaction v0-to-v2 migration**

Within an exclusive transaction create v2 tables, parse and canonicalize every legacy payload,
classify priority, sequence pending first and quarantine second, verify distinct UUID counts, drop legacy
tables, set `user_version=2`, and commit. Any exception rolls back the DDL/data migration. Never
rename, truncate, or recreate a failed legacy file.

- [ ] **Step 7: Preserve old outbox call sites and tests**

Change `outbox.py` into imports/compatibility wrappers for `LocalTelemetryStore` and its async adapter.
Update the old eviction test to require `LocalStoreCapacityError` and verify all previously persisted
pending rows survive; silent oldest-row eviction is no longer allowed.

- [ ] **Step 8: Run GREEN and commit Task 2**

```bash
uv run --project apps/agent pytest -q \
  apps/agent/tests/test_local_store.py \
  apps/agent/tests/test_outbox.py
uv run --project apps/agent ruff check apps/agent/src apps/agent/tests
uv run --project apps/agent mypy --strict apps/agent/src
git add apps/agent/src/aegisx_agent/local_store.py \
  apps/agent/src/aegisx_agent/outbox.py \
  apps/agent/tests/test_local_store.py \
  apps/agent/tests/test_outbox.py
git commit -m "feat(agent): persist telemetry in a local journal"
```

### Task 3: Atomic Delivery State and Async Runner Integration

**Files:**
- Modify: `apps/agent/src/aegisx_agent/local_store.py`
- Modify: `apps/agent/src/aegisx_agent/outbox.py`
- Modify: `apps/agent/src/aegisx_agent/runner.py`
- Modify: `apps/agent/tests/test_local_store.py`
- Modify: `apps/agent/tests/test_outbox.py`
- Modify: `apps/agent/tests/test_runner.py`

**Interfaces:**
- Produces `AsyncLocalTelemetryStore.open(path, max_events, max_payload_bytes)` and async wrappers for every delivery method.
- Produces `delivery_state(event_id: str) -> DeliveryState | None` for bounded diagnostics/tests.
- Produces `LegacyDeliveryStore` for a rolled-back v0 migration: it may deliver/quarantine existing
  legacy rows but exposes no append operation.
- `acknowledge(ids)` atomically transitions matching `PENDING` rows to `ACKED`, sets UTC acknowledgement, and removes them from `peek` without deleting journal rows.
- `quarantine(ids, reason)` atomically transitions rows to `QUARANTINED`; reason is restricted to `http_<status>` and 64 characters.
- `RunResult` adds `coverage_status: Literal["complete", "degraded"]` while retaining existing fields; `evicted` remains for API compatibility and is always zero.

- [ ] **Step 1: Write delivery-state tests**

```python
def test_acknowledge_keeps_event_in_journal_but_not_delivery_view(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    item = event(EVENT_ID, "process.started")
    store.enqueue([item])
    store.acknowledge([item.id])

    assert store.peek(10) == []
    assert store.count() == 0
    assert store.delivery_state(item.id) is DeliveryState.ACKED
```

Also cover unknown IDs, duplicate acknowledgement, quarantine, transaction rollback forced through a
SQLite trigger, restart ordering, async serialization, and cancellation waiting for worker completion.

- [ ] **Step 2: Run delivery-state RED**

```bash
uv run --project apps/agent pytest -q \
  apps/agent/tests/test_local_store.py \
  apps/agent/tests/test_outbox.py
```

Expected: ACK removes the old row rather than preserving it as `ACKED`, and async type is absent.

- [ ] **Step 3: Implement state transitions and async adapter**

Use one connection behind one `asyncio.Lock`; invoke synchronous operations through the existing
shielded `asyncio.to_thread` helper. `peek` selects only `PENDING ORDER BY sequence LIMIT ?`.
Acknowledgement/quarantine updates must commit in one explicit transaction and roll back on error.

When v0 migration raises `LocalStoreMigrationError`, open the untouched v0 file through
`LegacyDeliveryStore`, flush only its already-persisted rows with the existing delivery semantics,
do not collect/append a new batch, and report degraded coverage. A subsequent successful migration
remains idempotent; fallback never resets or rewrites the legacy schema.

- [ ] **Step 4: Write runner RED tests**

Test network-call ordering with a client that opens the SQLite file inside `send_events` and observes
the Event as `PENDING`. Test online leaves `ACKED`, offline leaves `PENDING`, 422 leaves
`QUARANTINED`, and capacity/write failure returns degraded coverage without calling the client.

- [ ] **Step 5: Integrate the runner minimally**

Open the async store with both configured bounds:

```python
store = await AsyncLocalTelemetryStore.open(
    settings.state_directory / "outbox.sqlite3",
    max_events=settings.max_outbox_events,
    max_payload_bytes=settings.local_telemetry_max_bytes,
)
```

Keep `_deliver_batch` recursion and server semantics unchanged. Catch only typed local-store failures,
emit no payload, return `delivery_status="deferred"`, `coverage_status="degraded"`, and never send an
Event that failed local append. Successful/offline normal paths report `coverage_status="complete"`.

- [ ] **Step 6: Run GREEN and commit Task 3**

```bash
uv run --project apps/agent pytest -q \
  apps/agent/tests/test_local_store.py \
  apps/agent/tests/test_outbox.py \
  apps/agent/tests/test_runner.py
uv run --project apps/agent ruff check apps/agent/src apps/agent/tests
uv run --project apps/agent mypy --strict apps/agent/src
git add apps/agent/src/aegisx_agent/local_store.py \
  apps/agent/src/aegisx_agent/outbox.py \
  apps/agent/src/aegisx_agent/runner.py \
  apps/agent/tests/test_local_store.py \
  apps/agent/tests/test_outbox.py \
  apps/agent/tests/test_runner.py
git commit -m "feat(agent): preserve acknowledged endpoint evidence"
```

### Task 4: Verification, Retention, Quota, and Coverage Gaps

**Files:**
- Modify: `apps/agent/src/aegisx_agent/local_types.py`
- Modify: `apps/agent/src/aegisx_agent/local_store.py`
- Modify: `apps/agent/tests/test_local_store.py`

**Interfaces:**
- Produces immutable `LocalEventTypeStats(event_type, count, payload_bytes, oldest_recorded_at, newest_recorded_at)`.
- Produces immutable `LocalDataStatus(policy_version, schema_version, logical_payload_bytes, database_file_bytes, event_count, pending_count, acknowledged_count, quarantined_count, coverage_gap_count, event_types)`.
- Produces immutable `LocalVerifyResult(valid, checked_events, first_bad_sequence, failure_category)`.
- Produces immutable `LocalPruneRuleReport(priority, cutoff, eligible_events, eligible_payload_bytes)` and `LocalPruneReport(policy_version, evaluation_time, rules)` with aggregate properties.
- Produces immutable `LocalPruneResult(policy_version, evaluation_time, deleted_events, deleted_payload_bytes, completed)`.
- Produces `data_status()`, `verify()`, `dry_run(evaluation_time)`, `prune(evaluation_time, batch_size=1000)`.
- Produces bounded coverage-gap recording plus atomic `coverage-gap.json` fallback/import.
- Verification returns the first bad global sequence as bounded metadata and never returns payload.

- [ ] **Step 1: Write verification and clock tests**

Assert valid checksums, modified payload/checksum detection, successful verification after retention,
non-decreasing `recorded_at` on clock rollback, `CLOCK_REGRESSION` recording, SQLite
`quick_check` failure handling, and absence of payload/secret fields in result objects.

- [ ] **Step 2: Run verification RED**

```bash
uv run --project apps/agent pytest -q \
  apps/agent/tests/test_local_store.py -k 'verify or clock or gap'
```

Expected: missing methods/types or assertions fail because verification and gaps are absent.

- [ ] **Step 3: Implement bounded verification and gaps**

Verification scans rows by global sequence, recomputes canonical payload bytes and SHA-256 checksums,
and stops at the first mismatch. Gaps in sequence are allowed after policy pruning. Gap categories are enums; messages are fixed
operator-safe strings. Keep at most 1,000 gap rows by merging the open gap and deleting only the oldest
closed row when inserting a new one.

If SQLite gap persistence fails, atomically replace `coverage-gap.json`, fsync file and directory, and
surface `coverage_status="degraded"`. Import and remove the sidecar only after a committed SQLite row.

- [ ] **Step 4: Write retention/quota RED tests**

At one-microsecond-before, exact, and one-microsecond-after cutoffs, assert only exact/older ACKED
rows are eligible. Assert pending/quarantined/unknown rows remain while expired ACKED rows can prune.
Apply twice for idempotency. Force failure during delete and prove the batch rolls back.
Use small injected test quotas to prove eligible BULK is pruned first and not-yet-expired SECURITY is
never evicted; capacity exhaustion records a gap and rejects the complete incoming batch.

- [ ] **Step 5: Implement retention and quota**

Validate public batch size `1..1000`. For each priority with a TTL, select eligible ACKED rows in
`(recorded_at, sequence)` order, delete at most one batch, and commit in one transaction. Quota
pressure calls the same policy path; it never
has a bypass that deletes younger evidence.

- [ ] **Step 6: Run GREEN and commit Task 4**

```bash
uv run --project apps/agent pytest -q apps/agent/tests/test_local_store.py
uv run --project apps/agent ruff check apps/agent/src apps/agent/tests
uv run --project apps/agent mypy --strict apps/agent/src
git add apps/agent/src/aegisx_agent/local_types.py \
  apps/agent/src/aegisx_agent/local_store.py \
  apps/agent/tests/test_local_store.py
git commit -m "feat(agent): bound and verify local telemetry evidence"
```

### Task 5: Agent Maintenance CLI and Top-level Launcher Commands

**Files:**
- Modify: `apps/agent/src/aegisx_agent/cli.py`
- Create: `apps/agent/tests/test_cli.py`
- Modify: `tools/launcher/src/aegisx_launcher/cli.py`
- Modify: `tools/launcher/src/aegisx_launcher/runtime.py`
- Modify: `tools/launcher/tests/test_project.py`
- Modify: `tools/launcher/tests/test_runtime.py`

**Interfaces:**
- Internal agent commands accept an injectable `Sequence[str]` and return integer exit codes.
- Top-level commands: `local-data-status`, `local-verify`, `local-prune --dry-run`, and `local-prune --apply --yes`.
- Runtime methods invoke `uv run --project apps/agent aegisx-agent <command>` without discovering Compose or starting PostgreSQL.
- Read-only commands do not acquire `LauncherState`; apply acquires it and refuses missing `--yes` before opening SQLite.

- [ ] **Step 1: Write agent CLI tests**

With an injected fake store, prove aggregate-only rendering, valid/invalid verification exit codes,
dry-run cannot call prune, unsafe apply returns 2, confirmed apply calls prune once, and output excludes
payload, command line, token and raw exception strings.

- [ ] **Step 2: Run agent CLI RED**

```bash
uv run --project apps/agent pytest -q apps/agent/tests/test_cli.py
```

Expected: parser rejects local maintenance commands and no injectable command runner exists.

- [ ] **Step 3: Implement internal CLI**

Refactor `main()` to call `run_command(argv, settings, store_factory)` without changing
`collect-once`/`run`. Capture one UTC evaluation time per dry-run/apply, render stable `key=value`
aggregates, and dispose the store in `finally`.

- [ ] **Step 4: Write launcher RED tests**

Assert exact argv for all four commands; patch provider discovery to raise if called. Assert status,
verify and dry-run bypass `LauncherState`; apply takes it; apply without `--yes` returns 2 before the
runtime method is called.

- [ ] **Step 5: Implement launcher dispatch**

Add choices and local prune flags without changing server `prune`. Runtime uses the existing bounded
`CommandRunner` with a 900-second first-sync budget, forwards stdout, and prints only
`CommandResult.diagnostic()` on failure. It does not call `_providers()` or `_start_postgres()`.

- [ ] **Step 6: Run GREEN and commit Task 5**

```bash
uv run --project apps/agent pytest -q apps/agent/tests/test_cli.py
AEGISX_AGENT_STATE_DIR="$(mktemp -d)" \
  uv run --project tools/launcher pytest -q tools/launcher/tests
uv run --project apps/agent ruff check apps/agent/src apps/agent/tests
uv run --project tools/launcher ruff check tools/launcher
uv run --project apps/agent mypy --strict apps/agent/src
uv run --project tools/launcher mypy --strict tools/launcher/src
git add apps/agent/src/aegisx_agent/cli.py \
  apps/agent/tests/test_cli.py \
  tools/launcher/src/aegisx_launcher/cli.py \
  tools/launcher/src/aegisx_launcher/runtime.py \
  tools/launcher/tests/test_project.py \
  tools/launcher/tests/test_runtime.py
git commit -m "feat(cli): expose local telemetry maintenance"
```

### Task 6: Documentation, User Demo, and Full Verification

**Files:**
- Modify: `docs/aegisx-cli-manual.md`
- Modify: `docs/agent.md`
- Modify: `docs/architecture.md`
- Modify: `docs/implementation-map.md`
- Modify: `docs/progress.md`
- Modify: `README.md`
- Modify: `scripts/check-foundation.sh`

**Interfaces:**
- Documents where endpoint evidence lives, what is and is not authoritative, exact commands, storage pressure, checksum limits, and the future Response boundary in beginner-oriented language.
- Foundation checks require all four local command literals and the approved spec/plan.

- [ ] **Step 1: Make foundation validation fail first**

Require these exact strings in `docs/aegisx-cli-manual.md`:

```text
aegisx local-data-status
aegisx local-verify
aegisx local-prune --dry-run
aegisx local-prune --apply --yes
```

Run `./scripts/check-foundation.sh`; expected failure occurs before documentation is updated.

- [ ] **Step 2: Update documentation**

Explain that this milestone mirrors agent-generated Events locally but still sends the same stream to
PostgreSQL. Explain `PENDING`/`ACKED`/`QUARANTINED`, logical versus physical bytes, coverage gaps,
permissions, unsigned-checksum limitations, backup warning, and why no Detection can directly block.
Update `docs/progress.md` after implementation evidence exists; do not claim selective sync/realtime.

- [ ] **Step 3: Run an isolated real two-cycle demo**

Use a temporary agent state directory and the running development API:

```bash
demo_state=$(mktemp -d)
AEGISX_AGENT_STATE_DIR="$demo_state" \
  uv run --project apps/agent aegisx-agent collect-once
AEGISX_AGENT_STATE_DIR="$demo_state" \
  uv run --project apps/agent aegisx-agent collect-once
AEGISX_AGENT_STATE_DIR="$demo_state" aegisx local-data-status
AEGISX_AGENT_STATE_DIR="$demo_state" aegisx local-verify
AEGISX_AGENT_STATE_DIR="$demo_state" aegisx local-prune --dry-run
```

Record only aggregate output. Remove the exact temporary directory after the demo; do not reset the
development PostgreSQL database or default agent state.

- [ ] **Step 4: Run full verification**

Create an exact temporary PostgreSQL database, migrate it to head, then run:

```bash
AEGISX_TEST_POSTGRES_URL="$test_database_url" \
  uv run --project apps/api pytest -q apps/api/tests
uv run --project apps/agent pytest -q apps/agent/tests
AEGISX_AGENT_STATE_DIR="$(mktemp -d)" \
  uv run --project tools/launcher pytest -q tools/launcher/tests

uv run --project apps/api ruff format --check apps/api
uv run --project apps/agent ruff format --check apps/agent
uv run --project tools/launcher ruff format --check tools/launcher
uv run --project apps/api ruff check apps/api
uv run --project apps/agent ruff check apps/agent
uv run --project tools/launcher ruff check tools/launcher
uv run --project apps/api mypy --strict apps/api/src
uv run --project apps/agent mypy --strict apps/agent/src
uv run --project tools/launcher mypy --strict tools/launcher/src

uv run --project apps/api alembic -c apps/api/alembic.ini current
uv run --project apps/api alembic -c apps/api/alembic.ini heads
docker compose --env-file .env.example config
podman compose --env-file .env.example config
./scripts/check-foundation.sh
git diff --check
```

Drop only the named temporary PostgreSQL database and isolated agent/launcher state after verification.

- [ ] **Step 5: Commit documentation and push only after all checks pass**

```bash
git add README.md docs/aegisx-cli-manual.md docs/agent.md docs/architecture.md \
  docs/implementation-map.md docs/progress.md scripts/check-foundation.sh
git commit -m "docs: document local endpoint telemetry journal"
git status --short
git push origin main
```

Expected status contains only the preserved user-owned untracked
`docs/cau-hoi-trien-khai-thuc-te.md`. Stop after the user demo and final report; do not begin selective
sync, realtime, Decision, or Response.
