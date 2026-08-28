# AegisX

AegisX is a lightweight, evidence-first endpoint, network, and Wi-Fi threat-detection and attack-validation platform for authorized Linux labs. It combines deterministic rules, risk scoring, event correlation, and a read-only AI investigator without claiming to be an antivirus, SIEM, or commercial EDR replacement.

## Evidence-first flow

```text
Telemetry -> Detection rules -> Risk score -> Correlation -> Incident
                                                               |
                                                               +-> AI investigation
                                                               +-> User notification
```

A single weak signal is not treated as proof of malware. Incidents preserve facts, evidence, hypotheses, uncertainty, and conclusions separately. AI receives curated incident evidence and cannot kill processes, delete files, modify firewall rules, or execute shell commands.

## Repository layout

```text
apps/api/       FastAPI backend (starts in Milestone 1)
apps/agent/     Linux endpoint agent (starts in Milestone 2)
apps/web/       Next.js interface (starts in Milestone 6)
packages/shared/ Versioned shared contracts
infrastructure/ Local infrastructure configuration
docs/           Architecture, security, and development documentation
scripts/        Repository checks and later safe validation helpers
```

## Current implementation

Milestone 0 is implemented: repository policies, documented application boundaries, a PostgreSQL 17 Compose service, foundation validation, and initial project documentation. No telemetry collection, API endpoints, detection logic, UI, AI integration, or validation scenarios exist yet.

See [progress](docs/progress.md) for verification evidence and known limitations.

## Prerequisites

- Fedora/Linux or a comparable Linux environment
- Git and Make
- Docker Engine with Compose, or rootless Podman plus a Compose provider
- Python 3.12 and Node.js 22 are documented for later milestones; Milestone 0 does not install application dependencies

## Setup

```bash
cp .env.example .env
make check
make db-up
```

On a rootless Podman setup, start its user socket once for the current login and override the Compose command:

```bash
systemctl --user start podman.socket
make CONTAINER_COMPOSE='podman compose' check
make CONTAINER_COMPOSE='podman compose' db-up
```

Check PostgreSQL and stop it without deleting the named data volume:

```bash
docker compose --env-file .env exec -T postgres pg_isready -U aegisx -d aegisx
make db-down
```

Replace `docker compose` with `podman compose` when using Podman. Development defaults bind PostgreSQL only to `127.0.0.1`. The password in `.env.example` is not suitable for shared or production environments.

## Development

`make check` validates the repository skeleton, whitespace, and resolved Compose configuration. Detailed commands and conventions are in [development documentation](docs/development.md). Each completed milestone must update [progress](docs/progress.md) with commands that were actually executed.

## Roadmap

The project proceeds sequentially from backend and Linux agent foundations through network telemetry, detection, correlation, minimal UI, realtime notifications, Wi-Fi monitoring, AI investigation, safe validation, and final hardening. The approved platform design is in `docs/superpowers/specs/`.

## Limitations and security assumptions

- Linux/Fedora is the primary target; Windows parity is not part of the initial implementation.
- All validation must run on owned devices or explicitly authorized lab systems.
- AegisX does not automatically remediate a host.
- Host command lines and process metadata may be sensitive and require deliberate retention controls in later milestones.
- Local Compose defaults are for development only and do not configure production TLS or credential management.
# AegisX
