# Development

## Environment

Copy `.env.example` to `.env` and change development credentials when necessary. Never commit `.env`. Toolchain targets are Python 3.12, Node.js 22, PostgreSQL 17, `uv`, and pnpm 10.

## One-command launcher

Install the repository-local launcher once, then run the stack from any directory:

```bash
./scripts/install-aegisx
aegisx
```

The default and explicit `aegisx run` commands open the Textual Operator Console in the current terminal after the API becomes ready. Keys `1`–`5` select object tabs, `r` refreshes the bounded read-only PostgreSQL view, and `q` exits the console and stops launcher-owned API/agent processes. Use `aegisx run --no-ui` when raw API/agent logs are required.

`aegisx` validates Compose, starts PostgreSQL, synchronizes the API and agent environments, applies Alembic migrations, starts FastAPI, waits for `/health/ready`, and then starts the host agent. It falls back from Docker to rootless Podman and starts `podman.socket` for the current user when required. It does not use root privileges or delete database volumes.

```bash
aegisx doctor
aegisx stop
AEGISX_COMPOSE_COMMAND='podman compose' aegisx
```

The agent intentionally runs on the host. Running it in the Compose network namespace would collect the container's process/network view instead of the monitored development host.

## Repository checks

```bash
make check
```

For rootless Podman:

```bash
systemctl --user start podman.socket
make CONTAINER_COMPOSE='podman compose' check
```

## Database lifecycle

```bash
make db-up
make db-logs
make db-down
```

These commands preserve the named PostgreSQL volume. Removing volumes is intentionally not part of a normal Make target.

## Milestone discipline

Inspect the repository, plan the bounded milestone, implement test-first where behavior is introduced, run required lint/type/test/build checks, fix root causes, update documentation, and record exact evidence in `docs/progress.md`. Do not mark a milestone complete while a required check is failing.
