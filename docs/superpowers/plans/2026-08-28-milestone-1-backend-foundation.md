# AegisX Milestone 1 Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a tested FastAPI backend that reports health/readiness, migrates PostgreSQL, registers devices, and idempotently ingests validated process/system telemetry.

**Architecture:** Keep one async FastAPI service with focused configuration, database, models, schemas, repositories, and route modules. Use application lifespan to initialize logging only; Alembic owns schemas and requests receive async SQLAlchemy sessions through dependency injection.

**Tech Stack:** Python 3.12, uv, FastAPI, Pydantic Settings, SQLAlchemy async, asyncpg, Alembic, structlog, pytest, pytest-asyncio, HTTPX, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-28-aegisx-platform-design.md`

## Global Constraints

- No `create_all()` in application code; Alembic is the schema authority.
- API input is typed and bounded; event payloads are discriminated by explicit `event_type`.
- Event IDs are client-generated UUIDs and unique, making ingestion retries idempotent.
- Device registration issues a one-time opaque token; only its SHA-256 digest is stored.
- Secrets and credentials are never logged.
- Tests use SQLite async only for repository/route isolation; PostgreSQL migration and runtime behavior are verified separately.

---

### Task 1: Python Project, Configuration, and Health

**Files:** Create `apps/api/pyproject.toml`, `apps/api/src/aegisx_api/{__init__,config,logging,main}.py`, `apps/api/src/aegisx_api/api/{__init__,router,health}.py`, `apps/api/tests/{conftest,test_health,test_config}.py`.

**Interfaces:** `Settings` exposes environment, log level, database URL, API metadata, and ingestion limits. `create_app(settings: Settings | None = None) -> FastAPI` produces the application. `GET /health/live` returns `{"status":"ok"}`; `GET /health/ready` checks the database and returns 503 with `{"status":"unavailable"}` on dependency failure.

- [ ] Write health and configuration tests first and run them to observe missing-module failures.
- [ ] Add a src-layout uv project with runtime and development dependencies.
- [ ] Implement settings, redacting structured logging, application factory, router, liveness, and readiness.
- [ ] Run focused tests, Ruff, and mypy until clean.

### Task 2: Database Models and Migration

**Files:** Create `apps/api/src/aegisx_api/db/{__init__,base,session}.py`, `apps/api/src/aegisx_api/models/{__init__,device,event}.py`, `apps/api/alembic.ini`, `apps/api/alembic/{env.py,script.py.mako,versions/0001_device_event.py}`, `apps/api/tests/{test_models,test_migrations}.py`.

**Interfaces:** `Base` uses SQLAlchemy declarative mapping. `Device` stores UUID, stable external identifier, name, platform facts, token digest, created/updated/last-seen timestamps, and active flag. `Event` stores UUID, device foreign key, schema version, timestamp, type, source, severity hint, validated JSON data/metadata, ingestion timestamp, and promoted process keys. `get_session()` yields `AsyncSession`.

- [ ] Write model constraint and migration tests first and verify expected failures.
- [ ] Implement SQLAlchemy naming conventions, async engine/session factory, and both relational models.
- [ ] Write an explicit initial Alembic migration with foreign keys, uniqueness, checks, and correlation indexes.
- [ ] Upgrade a fresh PostgreSQL database to head, inspect the revision, downgrade to base, and upgrade again.

### Task 3: Device Registration and Telemetry Ingestion

**Files:** Create `apps/api/src/aegisx_api/security.py`, `apps/api/src/aegisx_api/schemas/{__init__,device,event,error}.py`, `apps/api/src/aegisx_api/repositories/{__init__,devices,events}.py`, `apps/api/src/aegisx_api/api/{dependencies,devices,telemetry}.py`, `apps/api/tests/{test_device_api,test_telemetry_api}.py`.

**Interfaces:** `POST /api/v1/devices/register` accepts stable ID, name, OS, OS version, kernel, and architecture and returns device UUID plus a one-time bearer token. `POST /api/v1/telemetry/events` requires `Authorization: Bearer`, accepts 1-100 events, validates supported `system.status`, `process.started`, and `process.resource_usage` payloads, and returns accepted/duplicate counts. Token verification uses constant-time digest comparison.

- [ ] Write registration, authentication, validation, unknown-event, and duplicate-ingestion API tests first; confirm each fails for the missing behavior.
- [ ] Implement bounded schemas and evidence-safe error responses.
- [ ] Implement token generation/digest verification and focused repositories.
- [ ] Implement routes and register them under `/api/v1`.
- [ ] Run route tests plus the full unit suite until clean.

### Task 4: Runtime Verification and Documentation

**Files:** Modify `Makefile`, `.env.example`, `README.md`, `docs/{api,architecture,event-model,development,progress}.md`, `apps/api/README.md`; create `apps/api/Dockerfile` only if needed for reproducible API startup.

**Interfaces:** Root commands expose API sync, lint, type-check, test, migration, and development server operations. Documentation contains exact current endpoints, auth behavior, event schemas, migration commands, limitations, and verification evidence.

- [ ] Run `uv sync --project apps/api --all-groups`, Ruff, mypy, and pytest.
- [ ] Start PostgreSQL, run Alembic upgrade, start Uvicorn, verify liveness/readiness, register a device, ingest one real request, query persistence, and stop processes cleanly.
- [ ] Test malformed payload and invalid token responses against the running API.
- [ ] Update documentation with exact results and no planned feature presented as implemented.
- [ ] Re-run the full milestone checks after documentation changes.
