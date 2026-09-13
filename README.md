# AegisX

AegisX is an evidence-first Linux endpoint and network security monitoring project. It collects truthful telemetry, applies deterministic detection and correlation, and preserves evidence in explainable Incidents. It is built for authorized Linux labs and is not an antivirus, full SIEM, commercial EDR replacement, or guaranteed malware detector.

## Evidence-first flow

```text
Telemetry -> Detection -> CorrelationCandidate -> Incident
```

A single weak signal is not treated as proof of malware. Events, Detections, CorrelationCandidates, Incident workflow, disposition, and future response decisions remain separate concepts. AegisX does not execute response actions.

## Repository layout

```text
apps/api/       FastAPI backend (starts in Milestone 1)
apps/agent/     Linux endpoint agent (starts in Milestone 2)
apps/web/       Reserved; no web application is implemented
packages/shared/ Versioned shared contracts
infrastructure/ Local infrastructure configuration
docs/           Architecture, security, and development documentation
scripts/        Repository checks and later safe validation helpers
```

## Current implementation

Milestones through 6A are implemented: PostgreSQL-backed typed ingestion, a Linux process/system/network agent, deterministic Detection rules, a narrow CorrelationCandidate foundation, and Incident persistence/promotion infrastructure. No production Incident promotion policy exists for the current low-confidence listener candidate.

See [progress](docs/progress.md) for verification evidence and known limitations.

## Prerequisites

- Fedora/Linux or a comparable Linux environment
- Git, `uv`, and Python 3.12
- Docker Engine with Compose, or rootless Podman plus a Compose provider

## One-command local run

```bash
./scripts/install-aegisx
aegisx
```

The install step is required once per checkout. After that, `aegisx` can be called from any directory. It starts PostgreSQL, applies Alembic migrations, starts the API, waits for readiness, and then runs the host agent. Press `Ctrl+C` to stop the API and agent. A PostgreSQL service that was already running is preserved.

`aegisx run` opens the AegisX Operator Console directly in the terminal. Use number keys `1`–`5` to switch between Devices, Events, Detections, Candidates, and Incidents; press `r` to refresh and `q` to exit and stop launcher-owned processes. No browser is used.

Useful commands:

```bash
aegisx doctor
aegisx data-status
aegisx prune --dry-run
aegisx local-data-status
aegisx local-verify
aegisx local-prune --dry-run
aegisx stop
aegisx run --no-ui
```

`--no-ui` retains the log-oriented mode for headless development and troubleshooting.
See the [AegisX CLI manual](docs/aegisx-cli-manual.md) before using destructive maintenance commands.

The launcher tries Docker Compose and then rootless Podman Compose. On Podman systems it can start the current user's `podman.socket`; it never escalates privileges or deletes the named database volume. Override provider selection when required:

```bash
AEGISX_COMPOSE_COMMAND='podman compose' aegisx
```

Development defaults bind PostgreSQL only to `127.0.0.1`. The password in `.env.example` is not suitable for shared or production environments.

## Development

`make check` validates the repository skeleton, whitespace, and resolved Compose configuration. Detailed commands and conventions are in [development documentation](docs/development.md). Each completed milestone must update [progress](docs/progress.md) with commands that were actually executed.

## Roadmap

The next work is telemetry quality, correlation quality, contextual Incident scoring, and production Linux-agent deployment. AI Investigator is no longer planned. Detection-family priorities and false-positive requirements are tracked in [the detection backlog](docs/detection-backlog.md).

## Limitations and security assumptions

- Linux/Fedora is the primary target; Windows parity is not part of the initial implementation.
- All validation must run on owned devices or explicitly authorized lab systems.
- AegisX does not automatically remediate a host.
- Host command lines and process metadata may be sensitive. The private endpoint journal has
  evidence-protecting local retention and explicit maintenance controls; selective sync and
  scheduled server retention are not implemented.
- Local Compose defaults are for development only and do not configure production TLS or credential management.
- The current polling Python agent is a development implementation, not a portable production endpoint agent.
