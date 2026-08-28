# Development

## Environment

Copy `.env.example` to `.env` and change development credentials when necessary. Never commit `.env`. Toolchain targets are Python 3.12, Node.js 22, PostgreSQL 17, `uv`, and pnpm 10.

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
