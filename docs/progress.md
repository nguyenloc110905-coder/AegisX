# Progress

## Milestone 0 — Repository Foundation

Status: complete with Docker access limitation documented below.

### Completed work

- Initialized Git on branch `main`.
- Added repository formatting, ignore, environment, pre-commit, and toolchain policies.
- Added API, agent, web, and shared-contract boundaries without later-milestone code.
- Added PostgreSQL 17 Compose configuration with localhost-only binding, health check, 256 MiB limit, persistent volume, and SELinux-compatible read-only initialization mount.
- Added foundation validation, Make targets, README, and initial technical documentation.

### Tests executed

- `git check-ignore -q .env && test -z "$(git check-ignore .env.example)" && git diff --check` — passed.
- `docker compose --env-file .env.example config --quiet` — passed.
- `docker version --format '{{.Server.Version}}'` — client worked; daemon access denied because the current user is not in group `docker`.
- `podman compose --env-file .env.example up -d --wait postgres` — initially failed because SELinux denied the bind mount; passed after adding the `Z` relabel option.
- `podman compose --env-file .env.example exec -T postgres pg_isready -U aegisx -d aegisx` — passed, accepting connections.
- `podman compose --env-file .env.example exec -T postgres psql -U aegisx -d aegisx -v ON_ERROR_STOP=1 -c 'SELECT 1;'` — passed, returned one row.
- `podman compose --env-file .env.example down` — passed; `aegisx_postgres_data` remained present.
- `make CONTAINER_COMPOSE='podman compose' check` — passed; foundation script, whitespace validation, and Compose parsing all returned exit code 0.

### Known limitations

- Docker runtime commands fail for user `nguyenloc` because `/var/run/docker.sock` is owned by `root:docker` and the user is not a member of `docker`. Rootless Podman was used for successful runtime verification.
- Git identity is now configured locally and verified commits are pushed to `origin/main`.
- Application code and production authentication/TLS do not exist in Milestone 0.

### Technical decisions

- Use a modular monolith and exclude Redis until measured realtime scaling requires it.
- Bind development PostgreSQL to loopback only and preserve data across normal shutdown.
- Support both Docker Compose and rootless Podman Compose through an overridable Make variable.
- Keep planned behavior explicitly labeled in documentation.

### Next milestone

Milestone 1 — Backend Foundation: FastAPI configuration and logging, health/readiness, async SQLAlchemy, Alembic, Device and Event models, validated telemetry ingestion, and tests.

## Milestone 1 — Backend Foundation

Status: in progress.

### Completed work

- Added the Python 3.12 `uv` project, validated settings, structured logging, FastAPI factory, and liveness endpoint.
- Added async SQLAlchemy infrastructure plus Device and Event models with evidence and correlation fields.
- Added the explicit `0001_device_event` Alembic migration; application code does not use `create_all()`.

### Tests executed

- `pytest` model and migration tests — 3 passed.
- Ruff — passed.
- mypy — passed on 13 source files.
- PostgreSQL Alembic `upgrade head`, `downgrade base`, and second `upgrade head` — passed.
- PostgreSQL inspection — confirmed `alembic_version`, `devices`, and `events` tables.

### Remaining work

- Database readiness endpoint and session dependency.
- Device registration and token authentication.
- Typed, bounded, idempotent telemetry ingestion.
- Full HTTP/PostgreSQL runtime verification and synchronized API documentation.
