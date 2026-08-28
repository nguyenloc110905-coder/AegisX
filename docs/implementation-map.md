# AegisX Current Implementation Map

This document maps the source code after the pre-Milestone-4 alignment patch. It does not treat plans, backlogs, or README claims as implementation evidence.

## 1. Current status

The repository has working foundations, an async FastAPI ingestion backend, PostgreSQL migrations, and a Linux telemetry agent. Milestones 0-3 are implemented in source. Milestone 4 (detection engine) has not started.

### Implemented

- PostgreSQL 17 development service through Compose.
- FastAPI liveness/readiness, Linux device registration, bearer-token authentication, and typed idempotent telemetry ingestion.
- Async SQLAlchemy Device/Event persistence and two Alembic migrations.
- Linux system, process, and network snapshot collectors.
- Agent normalization, registration, local identity/credential persistence, bounded SQLite outbox/quarantine, batching, offline recovery, and periodic execution/backoff.
- Schema-version-1 events: `system.status`, `process.started`, `process.resource_usage`, `network.listener_observed`, and `network.connection_observed`.
- FastAPI shutdown disposal and automated real-PostgreSQL Device/Event integration coverage.

### Partially implemented

- Process closure/lifecycle beyond starts: the persisted baseline proves newly observed process identities, but no `process.exited` event is emitted.
- Network lifecycle: `NetworkCollector` truthfully names current socket observations; it does not calculate or claim opened/closed transitions.
- Operational logging: JSON cycle logging exists for the agent and structlog is configured in the API, but there is no request correlation middleware or centralized exception logging.
- Agent service lifecycle: continuous CLI execution exists, but no systemd unit/install/uninstall flow exists.
- API architecture: route handlers contain persistence logic directly; there are no repository or service modules.
- Integration coverage: the core Device/Event flow has automated PostgreSQL coverage; most fast API tests still use SQLite for isolation.

### Planned only / not implemented

- File, service, persistence, authentication-log, DNS, Wi-Fi, and LAN collectors.
- Detection rules, registry/packs, risk scoring, correlation, detections, incidents, incident timelines, and AI analysis.
- WebSocket, notifications, web application, attack-validation framework, coverage metrics, and systemd packaging.
- Device listing/status APIs, event query APIs, incident APIs, retention policy, token rotation/revocation API, TLS deployment, and API container image.

### Verified checks

- API: 15 fast pytest tests pass and one PostgreSQL integration test passes when configured; Ruff format/lint pass; mypy passes on 20 source files.
- Agent: 25 pytest tests pass; Ruff format/lint pass; mypy passes on 16 source files.
- Alembic exposes one head: `0002_network_fields`.

## 2. Important project tree

```text
AegisX/
├── compose.yaml                         # Local PostgreSQL 17 service, health check, volume, limits.
├── Makefile                             # Root commands for infrastructure, API, and agent.
├── .env.example                         # Development PostgreSQL/API settings contract.
├── apps/
│   ├── api/
│   │   ├── pyproject.toml               # API package, dependencies, pytest/Ruff/mypy policy.
│   │   ├── alembic.ini                  # Alembic configuration.
│   │   ├── alembic/
│   │   │   ├── env.py                   # Async migration environment and model metadata.
│   │   │   └── versions/
│   │   │       ├── 0001_device_event.py # Creates Device/Event storage.
│   │   │       └── 0002_network_fields.py # Adds indexed network correlation fields.
│   │   ├── src/aegisx_api/
│   │   │   ├── main.py                  # FastAPI factory and module-level ASGI app.
│   │   │   ├── config.py                # Pydantic API settings.
│   │   │   ├── logging.py               # API structlog configuration.
│   │   │   ├── security.py              # Device-token generation and SHA-256 digest.
│   │   │   ├── api/
│   │   │   │   ├── router.py            # Combines health/device/telemetry routers.
│   │   │   │   ├── health.py            # Liveness and database readiness routes.
│   │   │   │   ├── devices.py           # Device registration route and persistence.
│   │   │   │   ├── telemetry.py         # Batch deduplication and Event persistence.
│   │   │   │   └── dependencies.py      # Async sessions and bearer authentication.
│   │   │   ├── db/
│   │   │   │   ├── base.py              # Declarative base and constraint naming.
│   │   │   │   └── session.py           # Async engine/session construction.
│   │   │   ├── models/
│   │   │   │   ├── device.py            # Device SQLAlchemy model.
│   │   │   │   └── event.py             # Event SQLAlchemy model and indexes.
│   │   │   └── schemas/
│   │   │       ├── device.py             # Registration request/response models.
│   │   │       └── event.py              # Discriminated event payload/envelope models.
│   │   └── tests/                         # 15 fast tests plus one PostgreSQL integration test.
│   ├── agent/
│   │   ├── pyproject.toml                # Agent CLI package and quality configuration.
│   │   ├── src/aegisx_agent/
│   │   │   ├── cli.py                    # `collect-once` and `run` command entry point.
│   │   │   ├── config.py                 # Agent settings and resource bounds.
│   │   │   ├── identity.py               # Stable private endpoint UUID file.
│   │   │   ├── credentials.py            # Private API credential persistence.
│   │   │   ├── events.py                 # Observation/NormalizedEvent and normalizer.
│   │   │   ├── api_client.py             # Async registration/ingestion HTTP client.
│   │   │   ├── outbox.py                 # Bounded SQLite pending/quarantine storage.
│   │   │   ├── runner.py                 # Collect, queue, register, deliver, isolate errors.
│   │   │   ├── service.py                # Periodic loop and exponential backoff.
│   │   │   ├── logging.py                # Agent JSON logging configuration.
│   │   │   └── collectors/
│   │   │       ├── base.py               # Collector protocol.
│   │   │       ├── system.py             # Host/kernel/uptime/CPU/RAM snapshot.
│   │   │       ├── process.py            # Bounded process/resource snapshots.
│   │   │       └── network.py            # Bounded listener/connection snapshots.
│   │   └── tests/                         # 25 collector/client/outbox/runner tests.
│   └── web/README.md                      # Boundary note only; no web source exists.
├── packages/shared/README.md              # Boundary note only; no shared package exists.
└── docs/                                  # Design, progress, backlog, and this source map.
```

## 3. Conceptual pipeline map

### OS / System State

**Status: implemented.** `psutil`, `platform`, `socket`, `os`, and `time` read current Linux host state. Exact consumers are `SystemCollector.collect`, `ProcessCollector.collect`, and `NetworkCollector.collect` under `apps/agent/src/aegisx_agent/collectors/`.

### Collector

**Status: implemented for system/process/network; absent for other domains.** `Collector` in `collectors/base.py` is a structural `Protocol` with `collect()`. Concrete collectors return `Observation` objects. There is no lifecycle `start()` or `stop()` interface despite the original conceptual example.

### Normalizer

**Status: implemented, small.** `normalize_observation()` in `apps/agent/src/aegisx_agent/events.py` adds a random UUID, UTC timestamp, and schema version 1 to an `Observation`, producing `NormalizedEvent`. It does not perform event-type-specific validation; API validation provides that boundary later.

### Event

**Status: implemented at three layers.** Agent `NormalizedEvent` is a flexible transport model. API `EventEnvelope` plus its five discriminated subclasses in `schemas/event.py` perform typed validation. SQLAlchemy `Event` in `models/event.py` persists the validated payload and promoted correlation fields.

### Ingest API

**Status: implemented.** `POST /api/v1/telemetry/events` maps to `ingest_events()` in `api/telemetry.py`. It accepts a non-empty batch bounded by `telemetry_batch_limit`, requires an active device bearer token, deduplicates UUIDs, persists new events, updates `last_seen_at`, and returns accepted/duplicate counts.

### Validation

**Status: implemented for the five supported event types.** FastAPI/Pydantic validates `EventBatchRequest` and the `TelemetryEvent` discriminated union before the handler runs. IPv4/IPv6 addresses, port ranges, PID/resource ranges, schema version, event type, severity, and batch length are bounded. The agent-side `Observation` remains deliberately flexible.

### Database

**Status: implemented.** Async SQLAlchemy stores `Device` and `Event` in PostgreSQL. Alembic owns the production schema. API tests also create the same metadata in temporary SQLite databases for isolation.

### Detection Engine

**Status: not implemented.** No source package, rule interface, registry, evaluation call, or Detection model exists. `docs/detection-*` files are plans only.

### Risk Scoring

**Status: not implemented.** `severity_hint` is transported and stored, but no score calculation or risk category code exists.

### Correlation Engine

**Status: not implemented.** Indexed/promoted process and network fields prepare data for correlation, but no correlation function executes.

### Incident

**Status: not implemented.** There is no Incident model, route, timeline, or incident-event relation.

### AI Investigator

**Status: not implemented.** There is no provider interface, prompt, model, endpoint, or stored analysis.

### Notification / UI

**Status: not implemented.** There is no WebSocket route, desktop notification adapter, Next.js package, or UI code. `apps/web/README.md` is documentation only.

## 4. Most complete real execution flow

The most complete implemented flow is one agent collection cycle through PostgreSQL persistence.

1. `apps/agent/src/aegisx_agent/cli.py` — `main()` parses `collect-once` and constructs `AgentSettings`.
2. `apps/agent/src/aegisx_agent/runner.py` — `collect_once()` loads/creates `identity.json`, loads `credentials.json`, and opens `outbox.sqlite3` under the configured state directory.
3. `runner.py` — `SystemCollector`, `ProcessCollector`, and `NetworkCollector` read current OS state and return one or more `Observation` values.
4. `apps/agent/src/aegisx_agent/events.py` — `normalize_observation()` adds event UUID, UTC timestamp, and schema version.
5. `apps/agent/src/aegisx_agent/outbox.py` — `Outbox.enqueue()` writes every normalized event before network access and evicts oldest rows above the configured bound.
6. If credentials are missing, `runner.py` builds `DeviceProfile`; `AegisXClient.register()` sends it to `POST /api/v1/devices/register`.
7. `apps/api/src/aegisx_api/schemas/device.py` validates the registration body. `register_device()` in `api/devices.py` creates a random token, stores only its SHA-256 digest in `Device`, commits, and returns the plaintext token once.
8. `apps/agent/src/aegisx_agent/credentials.py` — `save_credentials()` stores device ID/token locally with mode `0600`.
9. `runner.py` reads oldest outbox batches. `AegisXClient.send_events()` sends JSON plus `Authorization: Bearer <token>` to `POST /api/v1/telemetry/events`.
10. `apps/api/src/aegisx_api/api/dependencies.py` — `get_database_session()` yields an `AsyncSession`; `get_current_device()` hashes the bearer token, queries an active Device, and performs `compare_digest` before accepting it.
11. `apps/api/src/aegisx_api/schemas/event.py` — `EventBatchRequest` and the discriminated `TelemetryEvent` union validate the complete body before handler execution.
12. `apps/api/src/aegisx_api/api/telemetry.py` — `ingest_events()` queries existing UUIDs, skips duplicates, maps typed payloads into JSON plus promoted columns, adds `Event` rows, updates device `last_seen_at`, and commits.
13. The API returns HTTP 202 with counts. `_deliver_batch()` in the agent acknowledges accounted event IDs, leaving zero pending rows on full success.
14. Network/timeout/429/5xx errors leave events pending. 400/422 responses recursively split batches and move isolated single bad events to quarantine. 401/403 propagate without deleting queued evidence.

## 5. FastAPI architecture

| Item | Source and symbol | Actual behavior |
|---|---|---|
| Entry point | `apps/api/src/aegisx_api/main.py: app` | Module-level ASGI app returned by `create_app()`; Uvicorn imports this object. |
| Application factory | `main.py: create_app()` | Resolves settings, configures logging, constructs engine/session factory in `app.state`, includes root router. |
| Router registration | `api/router.py: router` | Includes health directly and device/telemetry routers under `/api/v1`. |
| Dependency injection | `api/dependencies.py` | Request-state session factory and bearer-authenticated Device dependencies. |
| Configuration | `config.py: Settings`, `get_settings()` | Pydantic Settings reads `.env`/aliases; cached only when factory receives no explicit settings. |
| Logging | `logging.py: configure_logging()` | Configures structlog JSON processors globally. Route code currently emits no explicit structured application events. |
| Health | `api/health.py: liveness()`, `readiness()` | Liveness is process-only; readiness executes `SELECT 1` and converts every exception to HTTP 503. |
| Exception handling | Route-local only | Registration maps `IntegrityError` to 409; auth maps failure to 401; readiness maps failures to 503. No global exception handler/error envelope exists. |
| Lifespan | Implemented | FastAPI shutdown awaits disposal of `app.state.engine`. |

## 6. Database implementation

- `compose.yaml` runs `postgres:17-alpine`, binds only `127.0.0.1`, persists a named volume, mounts an SELinux-compatible read-only init directory, health-checks with `pg_isready`, limits memory to 256 MiB, and applies `no-new-privileges`.
- `Settings.database_url` defaults to `postgresql+asyncpg://...`; secrets are development defaults in `.env.example`.
- `db/session.py` uses `create_async_engine(..., pool_pre_ping=True)` and `async_sessionmaker(..., expire_on_commit=False)`. `session_scope()` exists but is currently unused; request sessions come from `get_database_session()`.
- `Device` has identity/platform fields, unique token digest, active flag, timestamps, and a one-to-many Event relationship.
- `Event` has envelope fields, JSON payload/metadata, process fields, network fields, and device/time/process/network indexes.
- No repository or service implementation exists. `register_device()` and `ingest_events()` access SQLAlchemy directly.
- `0001_device_event` creates the two tables; `0002_network_fields` adds network columns/indexes. Alembic async environment loads `Base.metadata` and settings.
- Fast persistence/API tests use SQLite. A marked integration test requires `AEGISX_TEST_POSTGRES_URL` and validates registration, authenticated ingestion, promoted fields, and cleanup against PostgreSQL after Alembic migration.

## 7. Agent implementation

| Capability | Status | Files / symbols |
|---|---|---|
| Base collector abstraction | Implemented | `collectors/base.py: Collector`; only `collect()`, no start/stop lifecycle. |
| SystemCollector | Implemented | `collectors/system.py: SystemCollector.collect()`. |
| ProcessCollector | Implemented for starts/resources | `collectors/process.py`; persisted `(PID, create_time)` baseline, bounded output, and permission/race handling. First scan is baseline-only. |
| NetworkCollector | Implemented as snapshots | `collectors/network.py`; TCP/UDP listeners/connections, optional PID, bounded output. |
| FileCollector | Not implemented | No source file/class. |
| ServiceCollector | Not implemented | No source file/class. |
| WifiCollector | Not implemented | No source file/class. |
| Normalization | Implemented | `events.py: normalize_observation()`. |
| API client | Implemented | `api_client.py: AegisXClient`; async register/send/HTTP classification. |
| Local queue | Implemented | `outbox.py: Outbox`; bounded private SQLite pending and quarantine tables. |
| Device identity | Implemented | `identity.py: load_or_create_identity()`; stable UUID, exclusive mode-0600 creation. |
| Credentials | Implemented | `credentials.py`; Pydantic model and no-follow mode-0600 write. |
| Periodic operation | Implemented | `service.py: run_periodically()`; bounded exponential delay and recovery reset. |
| systemd | Not implemented | No unit, installer, or lifecycle integration. |

## 8. Architectural divergences

| Classification | Divergence | Assessment |
|---|---|---|
| A | Detection, scoring, correlation, incidents, AI, notifications, and UI are absent. | Expected roadmap state; do not infer them from docs or indexed fields. |
| A | File/service/Wi-Fi/DNS/authentication/LAN telemetry is absent. | Dependencies for later detection packs are not built. |
| B | `api/telemetry.py: ingest_events()` combines deduplication, mapping, persistence, and device heartbeat updates. | Acceptable at current size; likely service/repository extraction point when detection hooks arrive. |
| B | `runner.py: collect_once()` combines identity, credentials, collector orchestration, queueing, registration, delivery, and error policy. | Working but already broad; should be reviewed before more agent subsystems accumulate. |
| C | The collector interface only exposes synchronous `collect()`, not `start()/stop()`. | Reasonable for polling snapshots; event-driven collectors may require a second interface later. |
| C | Agent transport models are flexible while API models are discriminated/typed. | Reasonable trust-boundary validation, but agent can queue invalid events that API later quarantines. |
| C | SQLite outbox calls are synchronous inside an async runner. | Simple and acceptable at present load, but can block the event loop under slow disk/large queues. |
| C | Network events are observations only; no persisted socket comparison exists. | Names are now truthful, but future opened/closed rules require explicit state tracking. |
| C | Most API tests use `Base.metadata.create_all()` with SQLite. | Useful unit isolation; the core flow now also has real PostgreSQL integration coverage. |
| D | Device token loss cannot self-recover: re-registration conflicts on unique external ID and there is no rotation/re-enrollment flow. | Operational gap that should be designed before wider deployment. |

## 9. Learning map

| Concept | Implemented? | File | What to understand |
|---|---|---|---|
| FastAPI | Yes | `apps/api/src/aegisx_api/main.py` | How an ASGI app is constructed and imported by Uvicorn. |
| Application factory | Yes | `main.py: create_app()` | How settings and shared database objects enter app state. |
| Router | Yes | `api/router.py` | How route groups and prefixes compose. |
| HTTP request | Yes | `api/devices.py`, `api/telemetry.py` | FastAPI parameter parsing, dependencies, status codes, response models. |
| Pydantic | Yes | `schemas/*.py`, agent `events.py` | Validation models, bounds, literals, discriminated unions, serialization. |
| Configuration | Yes | API `config.py`, agent `config.py` | Environment aliases, defaults, constraints, cached API settings. |
| Logging | Partial | API/agent `logging.py`, agent `service.py` | Structlog processors and the limited events currently emitted. |
| PostgreSQL | Yes | `compose.yaml` | Container configuration, health, volume, loopback exposure. |
| SQLAlchemy | Yes | API `db/`, `models/` | Declarative mappings, engine/session factory, relationships, indexes. |
| Async | Yes | API routes/client/runner | Async HTTP and database I/O; SQLite outbox itself remains synchronous. |
| Session | Yes | `api/dependencies.py: get_database_session()` | One async session dependency shared within a request dependency graph. |
| Model | Yes | `models/device.py`, `models/event.py` | Relational identity, fields, constraints, relationships. |
| Migration | Yes | `alembic/env.py`, `alembic/versions/` | Explicit schema evolution independent from application startup. |
| Device | Yes | model/schema/registration route; agent identity/credentials | Difference between external UUID, database UUID, token, and digest. |
| Event | Yes | agent `events.py`, API `schemas/event.py`, `models/event.py` | Flexible observation, normalized envelope, typed validation, persistence. |
| Collector | Partial domains | agent `collectors/` | Polling host state through injectable OS boundaries. |
| Normalizer | Yes | agent `events.py: normalize_observation()` | Adds transport identity/time/version; does not validate domain payload. |
| Ingest | Yes | `api/telemetry.py: ingest_events()` | Authentication, idempotency, mapping, commit, response counts. |
| Validation | Yes for five events | `schemas/event.py` | Discriminator selects the correct payload model before handler logic. |
| Detection | No | None | Read backlog only as future intent. |
| Correlation | No | None | Promoted columns are preparation, not a running engine. |
| Incident | No | None | No model, service, or endpoint. |
| WebSocket | No | None | No realtime server implementation. |
| AI | No | None | No provider or analysis code. |

## 10. Recommended reading order

1. `apps/agent/src/aegisx_agent/runner.py` — orchestration overview.
2. `apps/agent/src/aegisx_agent/events.py` — observation-to-event boundary.
3. `apps/agent/src/aegisx_agent/collectors/system.py`, then `process.py`, then `network.py`.
4. `apps/agent/src/aegisx_agent/outbox.py` and `api_client.py` — reliability and transport.
5. `apps/api/src/aegisx_api/main.py` and `api/router.py` — backend entry and routing.
6. `apps/api/src/aegisx_api/api/dependencies.py` — sessions and authentication.
7. `apps/api/src/aegisx_api/schemas/event.py` — authoritative ingest validation.
8. `apps/api/src/aegisx_api/api/telemetry.py` — request-to-database mapping.
9. `apps/api/src/aegisx_api/models/device.py` and `models/event.py`.
10. `apps/api/alembic/versions/0001_device_event.py` and `0002_network_fields.py`.
11. Corresponding tests under `apps/agent/tests/` and `apps/api/tests/` to see guaranteed behavior.
