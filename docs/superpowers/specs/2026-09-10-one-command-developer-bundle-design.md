# One-Command Developer Bundle Design

Status: approved for implementation by the user on 2026-09-10.

## Goal

After one explicit installation step, running `aegisx` from any directory starts the local AegisX development stack and keeps it attached to the terminal until interrupted.

This milestone packages the accepted Milestone 6A baseline. It does not implement Decision, AI, UI, notifications, response actions, new detection packs, or a production eBPF agent.

## Runtime boundary

The launcher runs:

1. PostgreSQL 17 through the repository's existing Compose service.
2. Alembic migrations through the API environment.
3. FastAPI on `127.0.0.1:8000` as a host process.
4. The Linux agent as a host process after API readiness succeeds.

The agent must remain a host process because containerizing it would change the `/proc` and network namespaces being observed. The launcher is a developer convenience, not production deployment or endpoint protection.

## Command surface

- `aegisx`: validate prerequisites, start the stack, stream API/agent output, and wait.
- `aegisx doctor`: perform read-only prerequisite, project-root, Compose, and configuration checks.
- `aegisx stop`: stop the repository PostgreSQL service and any launcher state that can be safely identified.
- `aegisx --help`: document behavior and limitations.

Installation uses `scripts/install-aegisx`, which calls `uv tool install --editable tools/launcher --force`. Installation is the unavoidable bootstrap step; ordinary use after that is the single command `aegisx`.

## Project discovery and configuration

The launcher locates the repository by searching upward from the current directory, then from its editable package location, for both `compose.yaml` and `apps/api/pyproject.toml`. `AEGISX_PROJECT_ROOT` may explicitly override discovery and must resolve to a valid AegisX checkout.

It uses `.env` when present and otherwise `.env.example`. It never copies, prints, or rewrites credentials. `AEGISX_COMPOSE_COMMAND` may override Compose selection using a shell-like argument string.

## Compose selection

The launcher considers `docker compose` and `podman compose` in that order unless overridden. A provider is usable only when command discovery and `compose config --quiet` succeed. Stack startup tries usable providers in order; a daemon permission/runtime failure falls back to the next provider. Error output is bounded and credential values are not echoed.

## Startup and shutdown

Startup is fail-fast and ordered:

```text
discover project -> prerequisites -> compose validation/start PostgreSQL
-> API/agent dependency sync -> Alembic upgrade head
-> start API -> wait for /api/v1/health/ready
-> start agent -> wait for signal or child failure
```

Readiness has a bounded timeout. The agent is never started against an unready API. A non-zero child exit stops the sibling and returns non-zero.

`SIGINT`/`SIGTERM` terminate the agent and API, wait for a bounded grace period, then kill only children that did not exit. PostgreSQL is stopped on exit only when the launcher started it; a service already running before invocation is left running. Named database volumes are never deleted.

## Safety and observability

- No `shell=True` and no interpolated shell command execution.
- No root escalation.
- No raw environment, token, password, Event payload, or command line logging.
- Startup stages use concise human-readable status messages.
- Failures identify the failed stage and give one actionable remediation.
- One launcher instance owns a private state file under the existing AegisX state directory; a live duplicate invocation fails clearly.
- A stale state file is replaced only after its recorded PID is proven absent.

## AI removal

The accepted `main` baseline contains no AI implementation. The external AI work is preserved only on `rescue/ai-work-20260910`. User-facing documentation must stop claiming AI is part of the current product or planned by this milestone.

## Tests and verification

Unit tests cover project discovery, environment selection, Compose override parsing, provider fallback, exact command construction, readiness success/timeout, child failure, signal cleanup, existing-PostgreSQL preservation, and stale/live launcher state.

Integration verification covers editable installation, `aegisx --help`, `aegisx doctor`, Compose config, real PostgreSQL startup, Alembic head, API readiness, one agent collection cycle, clean interruption, and invocation from outside the repository.

Full API and agent tests, Ruff, strict mypy, Alembic checks, Compose validation, whitespace, and git status are required before completion.

## Deferred work

- Telemetry/detection noise fixes from the 2026-09-04 audit.
- Correlation and production Incident policy improvements.
- Milestone 6B Decision/Policy.
- Go or Rust eBPF CO-RE agent and production systemd packaging.
- UI, notifications, response execution, endpoint isolation, and AI Investigator.

