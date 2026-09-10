# One-Command Developer Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install a tested `aegisx` command that starts and supervises PostgreSQL, migrations, FastAPI, and the host Linux agent.

**Architecture:** A dependency-free Python launcher discovers the editable repository, selects a working Compose provider, prepares the two uv environments, migrates PostgreSQL, supervises API and agent child processes, and performs bounded cleanup. It orchestrates existing components without changing telemetry, detection, correlation, or Incident semantics.

**Tech Stack:** Python 3.12 standard library, uv tool packaging, Docker/Podman Compose, FastAPI, Alembic, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-10-one-command-developer-bundle-design.md`

## Global Constraints

- Do not add AI, Decision, UI, notifications, response actions, endpoint isolation, or detection packs.
- Do not modify Milestone 6A scoring, lifecycle, evidence, or transaction semantics.
- The agent runs on the host, not inside a container.
- Never delete the PostgreSQL named volume.
- Never log secrets or use `shell=True`.
- Every behavior change follows test-first red/green verification.

---

### Task 1: Launcher package and discovery

**Files:**
- Create: `tools/launcher/pyproject.toml`
- Create: `tools/launcher/src/aegisx_launcher/__init__.py`
- Create: `tools/launcher/src/aegisx_launcher/cli.py`
- Create: `tools/launcher/src/aegisx_launcher/project.py`
- Create: `tools/launcher/tests/test_project.py`

**Interfaces:**
- Produces: `find_project_root(start: Path | None = None) -> Path`, `select_env_file(root: Path) -> Path`, and console entry point `aegisx`.

- [ ] Write discovery tests for cwd lookup, editable-package fallback, explicit override, invalid override, and `.env` preference.
- [ ] Run focused tests and verify failure because the package does not exist.
- [ ] Implement the package metadata and discovery functions with bounded upward traversal.
- [ ] Run focused tests and verify pass.
- [ ] Commit as `feat(launcher): add project discovery and command package`.

### Task 2: Command runner and Compose provider selection

**Files:**
- Create: `tools/launcher/src/aegisx_launcher/commands.py`
- Create: `tools/launcher/src/aegisx_launcher/compose.py`
- Create: `tools/launcher/tests/test_compose.py`

**Interfaces:**
- Produces: `CommandResult`, `CommandRunner`, `ComposeProvider`, `discover_compose_providers()`, and argument-list-only subprocess execution.

- [ ] Write tests for override parsing, docker/podman order, missing executable, config rejection, bounded diagnostics, and runtime fallback.
- [ ] Run focused tests and verify expected missing-interface failures.
- [ ] Implement command execution without `shell=True` and provider selection using `config --quiet`.
- [ ] Run focused tests and verify pass.
- [ ] Commit as `feat(launcher): add safe Compose provider selection`.

### Task 3: Runtime orchestration and process supervision

**Files:**
- Create: `tools/launcher/src/aegisx_launcher/runtime.py`
- Create: `tools/launcher/tests/test_runtime.py`
- Modify: `tools/launcher/src/aegisx_launcher/cli.py`

**Interfaces:**
- Produces: `AegisXRuntime.run() -> int`, `doctor() -> int`, `stop() -> int`, readiness polling, and bounded child termination.

- [ ] Write tests asserting exact sync/migrate/start order, readiness gating, provider fallback, child failure propagation, signal cleanup, and preservation of pre-existing PostgreSQL.
- [ ] Run focused tests and verify failures occur at missing runtime behavior.
- [ ] Implement orchestration using argv lists, `subprocess.Popen`, `urllib.request`, and monotonic bounded waits.
- [ ] Run focused tests and verify pass.
- [ ] Refactor only after green to keep command construction and supervision separate.
- [ ] Commit as `feat(launcher): supervise the local AegisX stack`.

### Task 4: Single-instance state and installer

**Files:**
- Create: `tools/launcher/src/aegisx_launcher/state.py`
- Create: `tools/launcher/tests/test_state.py`
- Create: `scripts/install-aegisx`
- Modify: `Makefile`

**Interfaces:**
- Produces: private atomic launcher state, live/stale PID validation, executable installer, and `make launcher-install`.

- [ ] Write tests for private state creation, duplicate live PID rejection, stale state replacement, ownership-safe cleanup, and no database-volume deletion command.
- [ ] Run focused tests and verify expected failures.
- [ ] Implement state management with mode `0600`, atomic replacement, and exact-PID ownership checks.
- [ ] Implement installer as an argv-safe `uv tool install --editable tools/launcher --force` wrapper.
- [ ] Run focused tests, Ruff, and strict mypy for the launcher.
- [ ] Commit as `feat(launcher): install the aegisx command safely`.

### Task 5: Documentation and real smoke test

**Files:**
- Modify: `README.md`
- Modify: `docs/development.md`
- Modify: `docs/implementation-map.md`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: installed `aegisx`, `aegisx doctor`, and `aegisx stop`.

- [ ] Remove current-product AI claims and document the exact bootstrap and one-command workflow.
- [ ] Install the editable launcher and verify `aegisx --help` from `/tmp`.
- [ ] Run `aegisx doctor` and validate Docker-to-Podman behavior on this host.
- [ ] Run the real stack, confirm PostgreSQL readiness, Alembic `0005_incident_foundation`, API readiness, and an agent telemetry cycle, then interrupt and verify bounded cleanup.
- [ ] Run API tests, agent tests, launcher tests, Ruff format/check, strict mypy, Alembic current/heads, Compose config, `git diff --check`, and status review.
- [ ] Commit as `docs: publish one-command developer workflow`.

