# Terminal Operator Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `aegisx run` open the real AegisX Textual operator console and own its complete local-service lifecycle.

**Architecture:** A read-only console repository maps accepted ORM models into display records. A Textual app renders those records. The existing launcher starts API/agent in the background and runs the console in the foreground, with `--no-ui` retaining log mode.

**Tech Stack:** Python 3.12, Textual, SQLAlchemy asyncio, asyncpg, pytest, pytest-asyncio, Ruff, mypy, uv.

**Spec:** `docs/superpowers/specs/2026-09-10-terminal-operator-console-design.md`

## Global Constraints

- Do not restore Gemini, AI, Decision/Policy, response, notifications, web UI, or fake dashboard data.
- Do not change Milestone 6A persistence or promotion semantics.
- Bound every console query and displayed field.
- Exit paths must clean up launcher-owned processes and preserve pre-existing PostgreSQL.

---

### Task 1: Read-only dashboard repository

**Files:**
- Create: `apps/api/src/aegisx_api/console/__init__.py`
- Create: `apps/api/src/aegisx_api/console/types.py`
- Create: `apps/api/src/aegisx_api/console/repository.py`
- Test: `apps/api/tests/console/test_repository.py`

**Interfaces:**
- Produces: `ConsoleRepository.load(limit: int = 200) -> DashboardSnapshot` and `close() -> None`.
- Produces immutable display rows for Device, Event, Detection, Candidate, and Incident.

- [ ] Write an async SQLite test that inserts one accepted model of each kind, loads a snapshot, and asserts counts, ordering, bounded rows, and absence of secret fields.
- [ ] Run the focused test and confirm it fails because the console package does not exist.
- [ ] Implement typed display records and bounded read-only SELECT queries.
- [ ] Run the focused test and confirm it passes.

### Task 2: Textual application

**Files:**
- Create: `apps/api/src/aegisx_api/console/app.py`
- Create: `apps/api/src/aegisx_api/console/main.py`
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/api/uv.lock`
- Test: `apps/api/tests/console/test_app.py`

**Interfaces:**
- Consumes: async snapshot loader and close callback.
- Produces: `AegisXConsole` and `aegisx-console` entry point.

- [ ] Add failing Textual pilot tests for populated, empty, refresh, tab, and bounded-error states.
- [ ] Add the bounded Textual dependency and implement the five-tab terminal layout with `r`, number-key, and `q` bindings.
- [ ] Implement a same-event-loop entry point that closes database resources in `finally`.
- [ ] Run console tests, Ruff, and mypy.

### Task 3: Launcher integration

**Files:**
- Modify: `tools/launcher/src/aegisx_launcher/cli.py`
- Modify: `tools/launcher/src/aegisx_launcher/runtime.py`
- Modify: `tools/launcher/tests/test_project.py`
- Modify: `tools/launcher/tests/test_runtime.py`

**Interfaces:**
- `AegisXRuntime.run(show_ui: bool = True) -> int`.
- `aegisx run --no-ui` passes `show_ui=False`; default and explicit `run` pass `True`.

- [ ] Add failing parser/dispatch and runtime tests for foreground console start, exit-code propagation, background process cleanup, and `--no-ui` compatibility.
- [ ] Extend safe process spawning without shell execution and implement the foreground-console supervision path.
- [ ] Run launcher tests, Ruff, and mypy.

### Task 4: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/development.md`
- Modify: `docs/implementation-map.md`
- Modify: `docs/progress.md`

- [ ] Document `aegisx run`, console keys, `--no-ui`, limitations, and the later cross-machine packaging boundary.
- [ ] Run API, agent, and launcher suites; real PostgreSQL migration/integration; Ruff; strict mypy; Compose validation; and whitespace checks.
- [ ] Install the editable launcher and run a real terminal smoke from outside the repository; verify `q`/interrupt cleanup.
- [ ] Commit logical changes only after current-tree verification is green.
