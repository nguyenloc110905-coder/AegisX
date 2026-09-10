# Telemetry Signal Quality Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AegisX quiet and truthful by default: transmit lifecycle transitions instead of repeated snapshots/metrics, detect and correlate proved listener openings, and show telemetry recency and coverage limits in the terminal console.

**Architecture:** Collectors retain complete private baselines but gate high-volume observational emission behind opt-in settings. The default Detection and correlation pipeline moves from listener snapshots to the already-proved `network.listener_opened` transition without rewriting historical evidence. Console health remains a read-only derivation from authenticated `last_seen_at`, while destructive development cleanup stays an explicit guarded launcher command.

**Tech Stack:** Python 3.12, psutil, Pydantic Settings, FastAPI, SQLAlchemy async, PostgreSQL 17, Textual 8, pytest, Ruff, strict mypy, Docker/Podman Compose.

**Spec:** `docs/superpowers/specs/2026-09-10-telemetry-signal-quality-hardening-design.md`

## Global Constraints

- Preserve accepted Event, Detection, CorrelationCandidate, and Incident transaction/failure boundaries.
- Do not rewrite or delete historical PostgreSQL evidence automatically.
- Do not restore the discarded external rule pack or add AI, notifications, response execution, endpoint isolation, allowlists, forensic drill-down, eBPF, or signed releases.
- `network.listener_opened` means presence changed from absent to present between consecutive complete snapshots; an observation alone never proves this.
- Risk values remain deterministic heuristic contributions, not malware probability.
- Use TDD for every behavior change and commit each task independently.

---

### Task 1: Make high-volume agent observations opt-in

**Files:**
- Modify: `apps/agent/src/aegisx_agent/config.py`
- Modify: `apps/agent/src/aegisx_agent/runner.py`
- Modify: `apps/agent/src/aegisx_agent/collectors/process.py`
- Modify: `apps/agent/src/aegisx_agent/collectors/network.py`
- Create: `apps/agent/tests/test_config.py`
- Modify: `apps/agent/tests/test_process_collector.py`
- Modify: `apps/agent/tests/test_network_collector.py`
- Modify: `apps/agent/tests/test_runner.py`
- Modify: `.env.example`

**Interfaces:**
- `ProcessCollector(..., emit_resource_usage: bool = False)` controls only `process.resource_usage` output.
- `NetworkCollector(..., emit_observations: bool = False)` controls only `*_observed` output.
- `AgentSettings.emit_process_resource_usage: bool = False` and `AgentSettings.emit_network_snapshot_observations: bool = False` are passed by `collect_once()`.
- Baseline comparison, state persistence, transition output, outbox, and delivery contracts remain unchanged.

- [x] **Step 1: Add failing settings tests**

```python
def test_high_volume_observations_are_disabled_by_default() -> None:
    settings = AgentSettings(_env_file=None)
    assert settings.emit_process_resource_usage is False
    assert settings.emit_network_snapshot_observations is False


def test_high_volume_observations_can_be_enabled_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AEGISX_EMIT_PROCESS_RESOURCE_USAGE", "true")
    monkeypatch.setenv("AEGISX_EMIT_NETWORK_SNAPSHOT_OBSERVATIONS", "true")
    settings = AgentSettings(_env_file=None)
    assert settings.emit_process_resource_usage is True
    assert settings.emit_network_snapshot_observations is True
```

- [x] **Step 2: Run the settings tests and confirm RED**

Run: `uv run --project apps/agent pytest apps/agent/tests/test_config.py -q`

Expected: fail because both settings fields are absent.

- [x] **Step 3: Add the two boolean settings**

```python
emit_process_resource_usage: bool = Field(
    default=False,
    validation_alias="AEGISX_EMIT_PROCESS_RESOURCE_USAGE",
)
emit_network_snapshot_observations: bool = Field(
    default=False,
    validation_alias="AEGISX_EMIT_NETWORK_SNAPSHOT_OBSERVATIONS",
)
```

Add both variables with value `false` to `.env.example`.

- [x] **Step 4: Add failing process collector tests**

Change lifecycle tests to expect no resource Event by default. Add one explicit opt-in test:

```python
def test_process_resource_usage_is_opt_in(tmp_path: Path) -> None:
    collector = ProcessCollector(
        process_iter=iterator([FakeProcess(process_info(42))]),
        state_path=tmp_path / "process-state.json",
        emit_resource_usage=True,
    )
    assert [event.event_type for event in collector.collect()] == ["process.resource_usage"]
```

- [x] **Step 5: Run the process collector tests and confirm RED**

Run: `uv run --project apps/agent pytest apps/agent/tests/test_process_collector.py -q`

Expected: default-output assertions fail until emission is gated.

- [x] **Step 6: Gate process resource Event construction**

Store `emit_resource_usage` in `ProcessCollector.__init__`. In `collect()`, append `_resource_observation()` only when it is true. Do not change identity enumeration, `snapshot_complete`, transition comparison, or `_save_state()`.

- [x] **Step 7: Add failing network collector tests**

Default baseline/repeated snapshots must be empty, while transitions remain:

```python
assert collector.collect() == []
entries.append(new_listener)
assert [event.event_type for event in collector.collect()] == ["network.listener_opened"]
assert collector.collect() == []
```

Add an opt-in collector test expecting the existing `listener_observed` and `connection_observed` records when `emit_observations=True`.

- [x] **Step 8: Run the network collector tests and confirm RED**

Run: `uv run --project apps/agent pytest apps/agent/tests/test_network_collector.py -q`

Expected: repeated observed Events are still emitted.

- [x] **Step 9: Gate network observation construction**

Store `emit_observations` in `NetworkCollector.__init__` and initialize:

```python
observations = (
    [self._observed(record) for record in records[: self._max_connections]]
    if self._emit_observations
    else []
)
```

Do not gate transition output or baseline replacement.

- [x] **Step 10: Prove runner propagation**

Update the existing default-collector runner test to patch the collector constructors and assert that `collect_once()` passes the two resolved settings to the matching constructor. Then pass the settings in `runner.py`.

- [x] **Step 11: Verify and commit Task 1**

Run:

```bash
uv run --project apps/agent pytest apps/agent/tests -q
uv run --project apps/agent ruff format --check apps/agent/src apps/agent/tests
uv run --project apps/agent ruff check apps/agent/src apps/agent/tests
uv run --project apps/agent mypy apps/agent/src/aegisx_agent
git diff --check
```

Commit:

```bash
git add .env.example apps/agent
git commit -m "fix(agent): make snapshot telemetry opt-in"
```

---

### Task 2: Detect and correlate proved listener openings

**Files:**
- Create: `apps/api/src/aegisx_api/detection/rules/listener_opened.py`
- Delete: `apps/api/src/aegisx_api/detection/rules/listener_observed.py`
- Modify: `apps/api/src/aegisx_api/detection/rules/__init__.py`
- Modify: `apps/api/src/aegisx_api/detection/defaults.py`
- Modify: `apps/api/src/aegisx_api/correlation/strategies/process_listener_activity.py`
- Modify: `apps/api/src/aegisx_api/services/correlation.py`
- Modify: `apps/api/tests/detection/test_rules.py`
- Modify: `apps/api/tests/detection/test_engine.py`
- Modify: `apps/api/tests/correlation/factories.py`
- Modify: `apps/api/tests/correlation/test_engine.py`
- Modify: `apps/api/tests/correlation/test_process_listener_activity.py`
- Modify: `apps/api/tests/integration/test_postgres_ingestion.py`

**Interfaces:**
- `ListenerOpenedRule.rule_id == "LISTENER_OPENED"` and `event_types == frozenset({"network.listener_opened"})`.
- `ProcessListenerActivityStrategy.required_rule_ids == frozenset({"PROCESS_STARTED", "LISTENER_OPENED"})`.
- Strategy ID and correlation-key canonical input stay `PROCESS_LISTENER_ACTIVITY|device_id|pid|started_at`.
- Historical `LISTENER_OBSERVED` rows are ignored but never mutated.

- [x] **Step 1: Replace rule tests first**

Write tests that independently assert:

```python
source = event(
    "network.listener_opened",
    {"protocol": "tcp", "local_ip": "127.0.0.1", "local_port": 8000, "pid": 42},
)
match = ListenerOpenedRule().evaluate(source)
assert match is not None
assert match.reason == (
    "TCP listener appeared at 127.0.0.1:8000 (PID 42) between complete snapshots."
)
assert match.evidence_event_ids == (source.id,)
assert ListenerOpenedRule.severity == "low"
assert ListenerOpenedRule.score_contribution == 5
```

Also assert malformed/irrelevant input returns `None`, Python development wording contains neither `malware` nor `suspicious`, and `create_default_engine().evaluate(listener_observed_event) == ()`.

- [x] **Step 2: Run detection tests and confirm RED**

Run: `uv run --project apps/api pytest apps/api/tests/detection -q`

Expected: `ListenerOpenedRule` cannot be imported and observed evidence still matches the default engine.

- [x] **Step 3: Implement and register `ListenerOpenedRule`**

Use the existing validation shape but support only `network.listener_opened`. Replace imports and default registry construction, then remove the unused observed-rule module.

- [x] **Step 4: Convert correlation fixtures and expectations**

Change listener fixtures to:

```python
rule_id="LISTENER_OPENED"
event_type="network.listener_opened"
```

Add a rejection test containing a `LISTENER_OBSERVED` Detection. Keep the known SHA-256 key literal unchanged to prove backward-compatible idempotency.

- [x] **Step 5: Run correlation tests and confirm RED**

Run: `uv run --project apps/api pytest apps/api/tests/correlation -q`

Expected: the current strategy still selects `LISTENER_OBSERVED` and rejects the new fixture.

- [x] **Step 6: Switch correlation selection to opened evidence**

Change `required_rule_ids`, listener extraction guard, `_RELEVANT_RULE_IDS`, `_evidence_for_anchor`, and neutral reason text. Do not change eligibility, confidence, score aggregation, Candidate key, savepoint, or persistence logic.

- [x] **Step 7: Add PostgreSQL ingestion coverage**

Create a registered Device, ingest a process-start Event and listener-opened Event with the same PID inside the configured window, and assert:

```python
assert detection_rule_ids == {"PROCESS_STARTED", "LISTENER_OPENED"}
assert candidate.strategy_id == "PROCESS_LISTENER_ACTIVITY"
assert candidate.confidence == "low"
assert candidate.aggregate_score == 5
assert set(candidate_detection_rule_ids) == {"PROCESS_STARTED", "LISTENER_OPENED"}
```

Retry the same Event UUIDs and assert Detection/Candidate counts do not increase. Ingest `network.listener_observed` separately and assert it persists only as an Event.

- [x] **Step 8: Verify and commit Task 2**

Run:

```bash
uv run --project apps/api pytest apps/api/tests/detection apps/api/tests/correlation -q
uv run --project apps/api pytest apps/api/tests/integration/test_postgres_ingestion.py -q -m integration
uv run --project apps/api ruff format --check apps/api/src apps/api/tests
uv run --project apps/api ruff check apps/api/src apps/api/tests
uv run --project apps/api mypy apps/api/src/aegisx_api
git diff --check
```

Commit:

```bash
git add apps/api/src/aegisx_api/detection apps/api/src/aegisx_api/correlation \
  apps/api/src/aegisx_api/services/correlation.py apps/api/tests
git commit -m "fix(detection): evaluate proved listener transitions"
```

---

### Task 3: Show telemetry recency and coverage limits truthfully

**Files:**
- Modify: `apps/api/src/aegisx_api/config.py`
- Modify: `apps/api/src/aegisx_api/console/types.py`
- Modify: `apps/api/src/aegisx_api/console/repository.py`
- Modify: `apps/api/src/aegisx_api/console/main.py`
- Modify: `apps/api/src/aegisx_api/console/app.py`
- Modify: `apps/api/tests/test_config.py`
- Modify: `apps/api/tests/console/test_repository.py`
- Modify: `apps/api/tests/console/test_app.py`
- Modify: `.env.example`

**Interfaces:**
- `Settings.device_stale_after_seconds: int`, default 90, range 5..86,400.
- `TelemetryStatus = Literal["recent", "stale", "never", "disabled"]`.
- `DeviceRow` carries `enrollment: Literal["enabled", "disabled"]` and `telemetry_status: TelemetryStatus` instead of exposing `is_active` as “Active”.
- `ConsoleRepository(..., stale_after: timedelta, now: Callable[[], datetime])` derives display state without database writes.

- [ ] **Step 1: Add failing configuration boundary tests**

Assert default 90, accepted values 5 and 86,400, and rejection at 4 and 86,401. Add `AEGISX_DEVICE_STALE_AFTER_SECONDS=120` to the environment override test.

- [ ] **Step 2: Run config tests and confirm RED**

Run: `uv run --project apps/api pytest apps/api/tests/test_config.py -q`

Expected: the new setting is absent.

- [ ] **Step 3: Add the bounded API/console setting**

```python
device_stale_after_seconds: int = Field(default=90, ge=5, le=86400)
```

Add `AEGISX_DEVICE_STALE_AFTER_SECONDS=90` to `.env.example`.

- [ ] **Step 4: Add failing repository status tests**

Use a fixed UTC instant. Insert four Devices: enabled at the exact 90-second boundary, enabled one microsecond older, enabled with no timestamp, and disabled with a recent timestamp. Assert statuses `recent`, `stale`, `never`, and `disabled`, and enrollment labels `enabled`, `enabled`, `enabled`, `disabled`.

- [ ] **Step 5: Run repository tests and confirm RED**

Run: `uv run --project apps/api pytest apps/api/tests/console/test_repository.py -q`

Expected: `DeviceRow` and `ConsoleRepository` do not yet expose derived status.

- [ ] **Step 6: Implement pure recency derivation**

Normalize naive SQLite test timestamps to UTC only for comparison. Derive:

```python
if not row.is_active:
    status = "disabled"
elif row.last_seen_at is None:
    status = "never"
elif row.last_seen_at >= current_time - self._stale_after:
    status = "recent"
else:
    status = "stale"
```

Pass `timedelta(seconds=settings.device_stale_after_seconds)` from console `main.py`.

- [ ] **Step 7: Add failing Textual assertions**

Assert the Device table columns include `Enrollment`, `Telemetry`, and `Last seen`, and do not include `Active`. Assert a persistent widget contains exactly:

```text
Polling telemetry only; AegisX does not prevent attacks and may miss activity between snapshots.
```

Assert the connected status says `rule matches are not automatic alerts`.

- [ ] **Step 8: Implement console wording/layout**

Add a two-line persistent coverage panel, render enrollment/telemetry values, and keep database error output secret-safe. Do not add raw payload or command-line drill-down.

- [ ] **Step 9: Verify and commit Task 3**

Run:

```bash
uv run --project apps/api pytest apps/api/tests/console apps/api/tests/test_config.py -q
uv run --project apps/api ruff format --check apps/api/src apps/api/tests
uv run --project apps/api ruff check apps/api/src apps/api/tests
uv run --project apps/api mypy apps/api/src/aegisx_api
git diff --check
```

Commit:

```bash
git add .env.example apps/api/src/aegisx_api/config.py \
  apps/api/src/aegisx_api/console apps/api/tests/console apps/api/tests/test_config.py
git commit -m "feat(console): show truthful telemetry recency"
```

---

### Task 4: Add an explicit guarded development reset

**Files:**
- Modify: `tools/launcher/src/aegisx_launcher/cli.py`
- Modify: `tools/launcher/src/aegisx_launcher/runtime.py`
- Modify: `tools/launcher/tests/test_project.py`
- Modify: `tools/launcher/tests/test_runtime.py`

**Interfaces:**
- CLI command: `aegisx dev-reset --yes`.
- `AegisXRuntime.dev_reset(*, confirmed: bool) -> int` returns nonzero without mutation on missing confirmation, non-development environment, no Compose provider, or all provider failures.
- CLI holds `LauncherState.default()` while executing reset, so another live launcher causes existing exit code 3 and no reset.
- Environment parsing checks process `AEGISX_ENV`/`AEGISX_ENVIRONMENT` first, then the selected env file, and treats an absent value as the API default `development`; explicit values other than `development` fail closed.

- [ ] **Step 1: Add failing CLI dispatch/refusal tests**

Extend the fake runtime with `dev_reset(confirmed: bool)`. Assert `main(["dev-reset"])` dispatches `False`, `main(["dev-reset", "--yes"])` dispatches `True`, and both use `LauncherState` ownership just like `run`.

- [ ] **Step 2: Run CLI tests and confirm RED**

Run: `uv run --project tools/launcher pytest tools/launcher/tests/test_project.py -q`

Expected: argparse rejects `dev-reset` and `--yes`.

- [ ] **Step 3: Add CLI syntax and ownership guard**

Add `dev-reset` to command choices and `--yes` as a boolean flag. Wrap only `run` and `dev-reset` in `LauncherState.default()`; dispatch confirmation to the runtime method.

- [ ] **Step 4: Add failing runtime safety tests**

Cover these literal outcomes:

- unconfirmed returns 2 and runner receives no calls;
- `AEGISX_ENV=production` in the process environment or selected env file returns 2 and runner receives no calls;
- development plus confirmation calls the first provider with `down --volumes --remove-orphans`;
- first provider failure falls back to the second;
- all failures return 1;
- success output explicitly says PostgreSQL evidence was removed and agent identity/outbox were preserved.

Use only `FakeRunner`; no test may invoke real Compose volume deletion.

- [ ] **Step 5: Run runtime tests and confirm RED**

Run: `uv run --project tools/launcher pytest tools/launcher/tests/test_runtime.py -q`

Expected: `AegisXRuntime.dev_reset` is absent.

- [ ] **Step 6: Implement fail-closed reset**

Read only the selected env file, accepting shell-style comments and optional quotes for `AEGISX_ENV` or `AEGISX_ENVIRONMENT`. Do not source or execute the file. After confirmation and environment checks, iterate validated providers and run:

```python
provider.argv(self._env_file, "down", "--volumes", "--remove-orphans")
```

Never touch `AEGISX_AGENT_STATE_DIR`.

- [ ] **Step 7: Verify and commit Task 4**

Run:

```bash
uv run --project tools/launcher pytest tools/launcher/tests -q
uv run --project tools/launcher ruff format --check tools/launcher/src tools/launcher/tests
uv run --project tools/launcher ruff check tools/launcher/src tools/launcher/tests
uv run --project tools/launcher mypy tools/launcher/src/aegisx_launcher
git diff --check
```

Commit:

```bash
git add tools/launcher
git commit -m "feat(launcher): guard development data reset"
```

---

### Task 5: Align documentation and run full verification

**Files:**
- Modify: `docs/event-model.md`
- Modify: `docs/agent.md`
- Modify: `docs/detection-engine.md`
- Modify: `docs/correlation-engine.md`
- Modify: `docs/threat-model.md`
- Modify: `docs/development.md`
- Modify: `docs/implementation-map.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Documentation must describe current defaults and evidence semantics, not planned eBPF or discarded external rules.
- Completion evidence records fresh command results only.

- [ ] **Step 1: Update semantic documentation**

Document opt-in observational Events, default transition-only collection, `LISTENER_OPENED`, unchanged low-confidence correlation, historical-row compatibility, recency labels, polling limitations, and guarded reset behavior. Remove stale statements that Incident is unimplemented while preserving the 6A boundaries.

- [ ] **Step 2: Run complete automated verification**

Run:

```bash
uv run --project apps/api pytest apps/api/tests -q
uv run --project apps/agent pytest apps/agent/tests -q
uv run --project tools/launcher pytest tools/launcher/tests -q
uv run --project apps/api ruff format --check apps/api/src apps/api/tests
uv run --project apps/api ruff check apps/api/src apps/api/tests
uv run --project apps/agent ruff format --check apps/agent/src apps/agent/tests
uv run --project apps/agent ruff check apps/agent/src apps/agent/tests
uv run --project tools/launcher ruff format --check tools/launcher/src tools/launcher/tests
uv run --project tools/launcher ruff check tools/launcher/src tools/launcher/tests
uv run --project apps/api mypy apps/api/src/aegisx_api
uv run --project apps/agent mypy apps/agent/src/aegisx_agent
uv run --project tools/launcher mypy tools/launcher/src/aegisx_launcher
docker compose --env-file .env.example config --quiet
podman compose --env-file .env.example config --quiet
git diff --check
```

- [ ] **Step 3: Verify PostgreSQL and Alembic without deleting development data**

Create a uniquely named isolated PostgreSQL database, set `DATABASE_URL` for API integration tests, run all integration tests, then verify:

```bash
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api alembic -c apps/api/alembic.ini current
uv run --project apps/api alembic -c apps/api/alembic.ini heads
```

Expected current/head: `0005_incident_foundation`. Drop only the uniquely named isolated database after success. Do not invoke `aegisx dev-reset --yes`.

- [ ] **Step 4: Run real operator smoke test**

Run `aegisx run`, verify the coverage warning and Device recency columns, press `r`, then `q`. Confirm exit code 0, no API/agent/console child remains, and no launcher ownership file remains.

- [ ] **Step 5: Audit post-upgrade signal volume**

Run two complete agent cycles against the development service without reset. Query rows created after the audit start timestamp and confirm:

- zero new `process.resource_usage` Events;
- zero new `network.listener_observed` or `network.connection_observed` Events;
- no new `LISTENER_OBSERVED` Detections;
- repeated unchanged snapshots create no listener-opened Detection;
- any emitted transition matches the documented baseline change.

- [ ] **Step 6: Record evidence and commit documentation**

Write exact fresh test counts and limitations in `docs/progress.md`, then run `git diff --check` and commit:

```bash
git add docs .env.example
git commit -m "docs: publish telemetry signal quality defaults"
```

- [ ] **Step 7: Final repository audit**

Run:

```bash
git status --short --branch
git log --oneline --decorate -8
git diff HEAD~4 --check
```

Confirm AI, notifications, response execution, allowlists, eBPF, and production Incident policies were not added.
