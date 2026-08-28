# AegisX Milestone 0 Repository Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a clean, reproducible AegisX monorepo foundation with documented tooling and a validated PostgreSQL development service.

**Architecture:** Create empty application boundaries for the API, agent, and web UI without implementing later milestones. Centralize developer commands in a root Makefile, keep Docker configuration under `infrastructure/docker`, and make documentation explicitly distinguish current capabilities from planned work.

**Tech Stack:** Git, Docker Compose, PostgreSQL 17, Python 3.12 with uv, Node.js 22 with pnpm 10, Markdown, POSIX shell, Make.

**Spec:** `docs/superpowers/specs/2026-08-28-aegisx-platform-design.md`

## Global Constraints

- Primary target: Fedora/Linux on an 8 GB RAM development machine.
- Repository layout: `apps/api`, `apps/agent`, `apps/web`, `packages/shared`, `infrastructure`, `docs`, and `scripts`.
- PostgreSQL is the only runtime service in Milestone 0; Redis is excluded.
- No endpoint collection, telemetry API, detection, correlation, UI, AI, or attack simulation is implemented in this milestone.
- Secrets remain outside Git; `.env.example` contains development placeholders only.
- Required checks must pass before `docs/progress.md` records the milestone as complete.

---

## Planned File Map

- `.editorconfig`: cross-language whitespace and newline policy.
- `.env.example`: non-secret PostgreSQL and future application configuration contract.
- `.gitignore`: Python, Node, IDE, test, build, environment, and local-data exclusions.
- `.pre-commit-config.yaml`: whitespace, YAML, TOML, secret-key, and large-file checks.
- `.tool-versions`: documented Python and Node toolchain versions.
- `Makefile`: stable entry points for setup, validation, database lifecycle, and repository checks.
- `README.md`: truthful project overview, architecture, setup, current status, and limitations.
- `compose.yaml`: root Compose entry point for local PostgreSQL.
- `apps/{api,agent,web}/README.md`: ownership and milestone boundary for each application.
- `packages/shared/README.md`: policy for versioned shared contracts.
- `infrastructure/docker/postgres/init/.gitkeep`: reserved idempotent database initialization directory.
- `scripts/check-foundation.sh`: executable, side-effect-free repository validation.
- `docs/*.md`: architecture, API, agent, event, detection, threat, validation, development, and progress skeletons with explicit planned status.

### Task 1: Repository Policy and Toolchain Contracts

**Files:**
- Create: `.editorconfig`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `.pre-commit-config.yaml`
- Create: `.tool-versions`

**Interfaces:**
- Consumes: the approved platform design and Fedora/Linux development constraint.
- Produces: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST_PORT`, `DATABASE_URL`, `AEGISX_ENV`, and `LOG_LEVEL` configuration names used by Compose and later milestones.

- [ ] **Step 1: Create formatting and toolchain policies**

Define UTF-8, LF, final newlines, four-space Python indentation, two-space YAML/JSON indentation, Python `3.12`, and Node `22`.

- [ ] **Step 2: Create the environment contract**

Use development-only values: database `aegisx`, user `aegisx`, password `aegisx_dev_only`, host port `5432`, async URL `postgresql+asyncpg://aegisx:aegisx_dev_only@localhost:5432/aegisx`, environment `development`, and log level `INFO`.

- [ ] **Step 3: Create ignore and pre-commit policies**

Ignore `.env` variants except `.env.example`, Python/Node caches, virtual environments, coverage/build output, local PostgreSQL data, editor state, and OS artifacts. Configure upstream pre-commit hooks for trailing whitespace, EOF, YAML/TOML checks, merge conflicts, private keys, and files larger than 1 MiB.

- [ ] **Step 4: Verify policy files**

Run: `git check-ignore -q .env && test -z "$(git check-ignore .env.example)" && git diff --check`

Expected: exit code 0 and no whitespace errors.

- [ ] **Step 5: Commit**

Run `git add .editorconfig .env.example .gitignore .pre-commit-config.yaml .tool-versions && git commit -m "chore: define repository policies"` only when Git identity is configured. Otherwise leave changes staged or unstaged and record the limitation.

### Task 2: Monorepo Boundaries and Foundation Validator

**Files:**
- Create: `apps/api/README.md`
- Create: `apps/agent/README.md`
- Create: `apps/web/README.md`
- Create: `packages/shared/README.md`
- Create: `infrastructure/docker/postgres/init/.gitkeep`
- Create: `scripts/check-foundation.sh`
- Create: `Makefile`

**Interfaces:**
- Consumes: configuration names from Task 1.
- Produces: `make check`, `make compose-config`, `make db-up`, `make db-down`, and `make db-logs` developer commands.

- [ ] **Step 1: Write a failing foundation check**

Create `scripts/check-foundation.sh` with `set -eu`; check every required directory and foundation file using explicit `test -d` and `test -f` statements; require `.env.example` to contain each configuration name; print `AegisX foundation checks passed.` only after all checks succeed.

- [ ] **Step 2: Run the checker before scaffolding**

Run: `sh scripts/check-foundation.sh`

Expected: non-zero exit because application boundary directories and files do not exist yet.

- [ ] **Step 3: Create focused boundary documentation**

Each application README states responsibility, non-responsibilities, intended runtime, and the milestone that first adds executable code. The shared package README permits only versioned schemas/contracts and forbids application business logic.

- [ ] **Step 4: Create root developer commands**

Make `check` run `sh scripts/check-foundation.sh`, `git diff --check`, and Compose validation. Database targets invoke the root `compose.yaml` and use `.env` when present.

- [ ] **Step 5: Run the checker after scaffolding**

Run: `make check`

Expected: foundation script and whitespace checks pass; Compose validation becomes testable after Task 3 creates `compose.yaml`.

- [ ] **Step 6: Commit**

Run `git add apps packages infrastructure scripts Makefile && git commit -m "chore: scaffold monorepo boundaries"` only when Git identity is configured.

### Task 3: PostgreSQL Development Service

**Files:**
- Create: `compose.yaml`

**Interfaces:**
- Consumes: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_HOST_PORT` from `.env` with the Task 1 development defaults as Compose fallbacks.
- Produces: Compose service `postgres`, named volume `postgres_data`, host port binding on `127.0.0.1`, and health check callable by later API work.

- [ ] **Step 1: Write Compose configuration**

Use `postgres:17-alpine`, `restart: unless-stopped`, a `pg_isready` health check, `stop_grace_period: 10s`, a named data volume, initialization-directory mount, and `127.0.0.1:${POSTGRES_HOST_PORT:-5432}:5432`. Set a 256 MiB memory limit and `no-new-privileges:true`; do not expose PostgreSQL on all interfaces.

- [ ] **Step 2: Validate resolved Compose configuration**

Run: `docker compose --env-file .env.example config --quiet`

Expected: exit code 0.

- [ ] **Step 3: Start PostgreSQL and wait for health**

Run: `docker compose --env-file .env.example up -d --wait postgres`

Expected: service `postgres` reaches healthy state. If Docker is unavailable, capture the exact environmental blocker and still complete static validation.

- [ ] **Step 4: Verify database access**

Run: `docker compose --env-file .env.example exec -T postgres pg_isready -U aegisx -d aegisx` and `docker compose --env-file .env.example exec -T postgres psql -U aegisx -d aegisx -v ON_ERROR_STOP=1 -c 'SELECT 1;'`

Expected: `accepting connections` and one row containing `1`.

- [ ] **Step 5: Stop without deleting data**

Run: `docker compose --env-file .env.example down`

Expected: containers and network stop; named volume remains recoverable.

- [ ] **Step 6: Commit**

Run `git add compose.yaml infrastructure/docker/postgres/init/.gitkeep && git commit -m "chore: add local PostgreSQL service"` only when Git identity is configured.

### Task 4: Foundation Documentation and Final Verification

**Files:**
- Create: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/event-model.md`
- Create: `docs/detection-engine.md`
- Create: `docs/agent.md`
- Create: `docs/api.md`
- Create: `docs/threat-model.md`
- Create: `docs/validation.md`
- Create: `docs/development.md`
- Create: `docs/progress.md`
- Modify: `scripts/check-foundation.sh`

**Interfaces:**
- Consumes: verified commands and boundaries from Tasks 1-3.
- Produces: the onboarding contract and the authoritative Milestone 0 completion record.

- [ ] **Step 1: Write truthful project documentation**

README covers vision, evidence-first flow, monorepo layout, prerequisites, environment setup, PostgreSQL commands, repository validation, currently implemented features, roadmap, limitations, and authorized-use assumptions. Skeleton documents describe agreed contracts but label unimplemented behavior as planned.

- [ ] **Step 2: Extend foundation validation**

Require all documentation files, boundary READMEs, Compose file, Makefile, and executable `scripts/check-foundation.sh`. Search README and progress documentation for the Milestone 0 status labels.

- [ ] **Step 3: Run all available checks**

Run: `make check`

Expected: foundation, whitespace, and Compose configuration checks pass.

Run: `git diff --check && git status --short`

Expected: no whitespace errors; status lists only intentional project files.

- [ ] **Step 4: Update progress evidence**

Record completed files, exact commands and outcomes, known environmental limitations, architectural decisions, and Milestone 1 as next. Mark Docker runtime verification complete only if the health and SQL checks actually passed.

- [ ] **Step 5: Re-run checks after documentation update**

Run: `make check`

Expected: exit code 0 with `AegisX foundation checks passed.`

- [ ] **Step 6: Commit**

Run `git add README.md docs scripts/check-foundation.sh && git commit -m "docs: document repository foundation"` only when Git identity is configured. Do not fabricate an identity to force a commit.
