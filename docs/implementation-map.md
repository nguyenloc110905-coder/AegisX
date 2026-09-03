# AegisX Current Implementation Map

This document maps the source code through the in-progress Milestone 5B hardening work. It does not treat plans, backlogs, or README claims as implementation evidence.

## 1. Current status

The repository has working foundations, an async FastAPI ingestion backend, PostgreSQL migrations, a Linux telemetry agent, the Milestone 4 detection foundation with its first two rules, and a narrow Milestone 5A correlation foundation. Later detection packs and incident workflow have not started.

### Implemented

- PostgreSQL 17 development service through Compose.
- FastAPI liveness/readiness, Linux device registration, bearer-token authentication, and typed idempotent telemetry ingestion.
- Async SQLAlchemy Device/Event/Detection/CorrelationCandidate persistence and four Alembic migrations.
- Linux system snapshots plus process and network snapshot-transition collectors.
- Agent normalization, registration, local identity/credential persistence, bounded SQLite outbox/quarantine, batching, offline recovery, and periodic execution/backoff.
- Schema-version-1 events: system status; process started/exited/resource usage; and network listener/connection observed/opened/closed.
- FastAPI shutdown disposal and automated real-PostgreSQL Device/Event/Detection/CorrelationCandidate integration coverage.
- Modular rule registry, rule-agnostic Detection Engine, deterministic scoring, transactional Detection persistence, and `PROCESS_STARTED`/`LISTENER_OBSERVED` rules.
- Deterministic `PROCESS_LISTENER_ACTIVITY` correlation with bounded evidence loading, a configurable inclusive window, relational Candidate evidence, savepoint-isolated failure handling, and one Candidate per canonical process identity.

### Partially implemented

- Process lifecycle completeness under OS races: starts and exits require complete consecutive snapshots, so any inaccessible/vanished record deliberately defers lifecycle transitions until a later complete comparison.
- Network lifecycle fidelity depends on complete snapshots; malformed or denied OS data intentionally defers transition comparison.
- Operational logging: JSON cycle logging exists for the agent and structlog is configured in the API, but there is no request correlation middleware or centralized exception logging.
- Agent service lifecycle: continuous CLI execution exists, but no systemd unit/install/uninstall flow exists.
- API architecture: telemetry ingestion has a service boundary; device registration still persists directly in its route and there are no repository modules.
- Integration coverage: the core Device/Event/Detection/CorrelationCandidate flow has automated PostgreSQL coverage; most fast API tests still use SQLite for isolation.

### Planned only / not implemented

- File, service, persistence, authentication-log, DNS, Wi-Fi, and LAN collectors.
- Later detection packs, device-level risk aggregation, incidents, incident timelines, and AI analysis.
- WebSocket, notifications, web application, attack-validation framework, coverage metrics, and systemd packaging.
- Device listing/status APIs, event query APIs, incident APIs, retention policy, token rotation/revocation API, TLS deployment, and API container image.

### Verified checks

- API: 51 pytest cases passed with PostgreSQL integration enabled, including the real Candidate flow; Ruff format/lint passed; strict mypy passed on 43 source files.
- Agent: 25 pytest cases passed; Ruff format/lint passed; strict mypy passed on 16 source files.
- PostgreSQL Alembic `upgrade head`, `current`, and `heads` reached the single `0004_correlation_foundation (head)`.

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
│   │   │       ├── 0002_network_fields.py # Adds indexed network correlation fields.
│   │   │       ├── 0003_detection_foundation.py # Creates Detection storage.
│   │   │       └── 0004_correlation_foundation.py # Creates Candidate and evidence storage.
│   │   ├── src/aegisx_api/
│   │   │   ├── main.py                  # FastAPI factory and module-level ASGI app.
│   │   │   ├── config.py                # Pydantic API settings.
│   │   │   ├── logging.py               # API structlog configuration.
│   │   │   ├── security.py              # Device-token generation and SHA-256 digest.
│   │   │   ├── detection/                # Rule contract, registry, engine, scoring, first rules.
│   │   │   ├── correlation/              # Strategy contract, registry, engine, process/listener strategy.
│   │   │   ├── services/                 # Transactional telemetry/detection ingestion and Candidate persistence.
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
│   │   │   │   ├── event.py             # Event SQLAlchemy model and indexes.
│   │   │   │   ├── detection.py         # Detection evidence and score contributions.
│   │   │   │   └── correlation.py       # Candidate model and relational evidence associations.
│   │   │   └── schemas/
│   │   │       ├── device.py             # Registration request/response models.
│   │   │       └── event.py              # Discriminated event payload/envelope models.
│   │   └── tests/                         # 50 non-integration cases across API test modules plus one PostgreSQL integration case.
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

**Status: implemented for the ten supported event types.** FastAPI/Pydantic validates `EventBatchRequest` and the `TelemetryEvent` discriminated union before the handler runs. IPv4/IPv6 addresses, port ranges, PID/resource ranges, schema version, event type, severity, and batch length are bounded. The agent-side `Observation` remains deliberately flexible.

### Database

**Status: implemented.** Async SQLAlchemy stores `Device`, `Event`, `Detection`, and `CorrelationCandidate` in PostgreSQL. Alembic owns the production schema. API tests also create the same metadata in temporary SQLite databases for isolation.

### Detection Engine

**Status: foundation implemented.** `detection/rules/base.py` defines the contract; `registry.py` indexes explicit rule registrations; `engine.py` evaluates only relevant rules; `defaults.py` composes the process/listener rules. `TelemetryIngestionService` evaluates each new Event and persists its Detections in the authoritative outer transaction. Detection is not an Incident.

### Risk Scoring

**Status: foundation implemented.** Every rule match carries a deterministic contribution persisted on its Detection. `calculate_risk_score()` sums results and clamps at 100. The Candidate strategy separately sums unique related Detection contributions and clamps at 100. Neither is malware probability or a persisted device-level risk aggregate.

### Correlation Engine

**Status: Milestone 5A foundation implemented.** `correlation/` contains a registry-indexed engine and the `PROCESS_LISTENER_ACTIVITY` strategy. `services/correlation.py` loads same-device, bounded relevant evidence and persists one idempotent Candidate per `(strategy_id, device_id, pid, started_at)`. The window is `Settings.correlation_window_seconds` (default 300 seconds; inclusive). Multiple eligible canonical process identities make the result ambiguous. A nested savepoint isolates correlation failures so valid Event/Detection evidence still commits. See [correlation-engine.md](correlation-engine.md). Correlation is neither an Incident nor an attack conclusion.

### Detection

**Status: implemented.** `models/detection.py` stores the source Event FK, Device FK, rule, timestamp, severity, score contribution, reason, and evidence UUIDs. Alembic `0003_detection_foundation` owns the table. `models/correlation.py` stores Candidate metadata and Candidate-to-Detection/Event evidence relations under `0004_correlation_foundation`; a Candidate is not an Incident.

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
12. `apps/api/src/aegisx_api/services/telemetry_ingestion.py` — the service skips duplicate UUIDs, maps new Events, invokes the Detection Engine, sets device `last_seen_at`, flushes Event/Detection evidence, runs correlation in a nested savepoint, and commits the authoritative outer transaction. A correlation-only failure logs every accepted triggering Event ID (including non-detections) and leaves Event/Detection evidence committed.
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
- No repository modules exist. `register_device()` still accesses SQLAlchemy directly, while `TelemetryIngestionService` owns the transactional telemetry/detection/correlation persistence flow.
- `0001_device_event` creates Device/Event, `0002_network_fields` adds network columns/indexes, `0003_detection_foundation` creates Detection storage, and `0004_correlation_foundation` creates Candidate/evidence storage. Alembic async environment loads `Base.metadata` and settings.
- Fast persistence/API tests use SQLite. A marked integration test requires `AEGISX_TEST_POSTGRES_URL` and validates registration, authenticated ingestion, promoted fields, Candidate evidence/idempotency, and cleanup against PostgreSQL after Alembic migration.

## 7. Agent implementation

| Capability | Status | Files / symbols |
|---|---|---|
| Base collector abstraction | Implemented | `collectors/base.py: Collector`; only `collect()`, no start/stop lifecycle. |
| SystemCollector | Implemented | `collectors/system.py: SystemCollector.collect()`. |
| ProcessCollector | Implemented for starts/exits/resources | `collectors/process.py`; atomic persisted `(PID, create_time)` baseline, bounded detail output with a complete identity scan, and conservative permission/race handling. First scan is baseline-only. |
| NetworkCollector | Implemented for observations/transitions | `collectors/network.py`; TCP/UDP listener/connection observations, endpoint-presence opened/closed comparison, optional PID attributes, atomic baseline, and bounded output. |
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
| A | Incidents, AI, notifications, UI, and later detection packs are absent. | Expected roadmap state; do not infer them from the narrow correlation foundation. |
| A | File/service/Wi-Fi/DNS/authentication/LAN telemetry is absent. | Dependencies for later detection packs are not built. |
| B | `runner.py: collect_once()` combines identity, credentials, collector orchestration, queueing, registration, delivery, and error policy. | Working but already broad; should be reviewed before more agent subsystems accumulate. |
| C | The collector interface only exposes synchronous `collect()`, not `start()/stop()`. | Reasonable for polling snapshots; event-driven collectors may require a second interface later. |
| C | Agent transport models are flexible while API models are discriminated/typed. | Reasonable trust-boundary validation, but agent can queue invalid events that API later quarantines. |
| C | SQLite outbox calls are synchronous inside an async runner. | Simple and acceptable at present load, but can block the event loop under slow disk/large queues. |
| C | Network events are observations only; no persisted socket comparison exists. | Names are now truthful, but future opened/closed rules require explicit state tracking. |
| C | Most API tests use `Base.metadata.create_all()` with SQLite. | Useful unit isolation; the core flow now also has real PostgreSQL integration coverage. |
| C | The correlation model relationship test reads objects held in the same SQLAlchemy identity map. | Constraints and PostgreSQL integration are covered, but an independent fresh-session ORM round-trip test is deferred. |
| C | Correlation logs all accepted batch Event IDs and persists a generic hardcoded reason for the first strategy. | Diagnostic IDs can include non-detections; future strategy-specific reasons need a result-level reason contract. |
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
| Detection | Foundation | `detection/`, `services/telemetry_ingestion.py`, `models/detection.py` | Pure rules, indexed selection, result mapping, and same-transaction persistence. |
| Correlation | Foundation | `correlation/`, `services/correlation.py`, `models/correlation.py` | Deterministic, bounded process/listener Candidate creation; not an Incident or attack conclusion. |
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
10. The four revisions under `apps/api/alembic/versions/`, ending at `0004_correlation_foundation.py`.
11. Corresponding tests under `apps/agent/tests/` and `apps/api/tests/` to see guaranteed behavior.
