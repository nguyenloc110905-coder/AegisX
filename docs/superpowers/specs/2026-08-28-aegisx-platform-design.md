# AegisX Platform Design

## Purpose

AegisX is a lightweight, evidence-first security monitoring and attack-validation platform for an authorized Linux lab. It collects endpoint, network, and later Wi-Fi telemetry; applies deterministic detection and correlation; creates explainable incidents; and invokes a read-only AI investigator only for curated incident evidence.

The first implementation targets Fedora/Linux and a development machine with 8 GB RAM. It is not an antivirus, SIEM, EDR replacement, or offensive platform.

## Scope and Delivery Strategy

Development follows the twelve milestones numbered 0 through 11 in the project brief, from repository foundation through hardening and final demonstration. Milestones are completed sequentially. A milestone is complete only after its implementation, relevant linting, type checks, tests/builds, documentation, and `docs/progress.md` entry have been verified.

Each milestone must inspect the existing repository before changing it. Later milestones may refine interfaces established earlier, but must not silently expand the product into a distributed platform or introduce infrastructure without demonstrated need.

## Architecture

AegisX uses a monorepo and a modular-monolith backend:

```text
apps/
  api/       FastAPI application and backend modules
  agent/     Independent Linux endpoint agent
  web/       Next.js user interface
packages/
  shared/    Versioned contracts and cross-application artifacts
infrastructure/
  docker/    Local infrastructure configuration
docs/        Architecture, security, operation, and progress documents
scripts/     Development and safe validation scripts
```

The API remains one deployable service. Device management, ingestion, detection, correlation, incidents, realtime delivery, and AI investigation are internal modules with explicit boundaries. The endpoint agent and web UI are separate processes. PostgreSQL is the system of record. Redis is excluded initially and may be introduced only if verified multi-process realtime requirements cannot be met cleanly without it.

## Technology Baseline

- Python 3.12 with `uv` for the API and agent.
- FastAPI, Pydantic, SQLAlchemy async, Alembic, and PostgreSQL.
- Ruff, mypy, and pytest for Python quality and testing.
- Next.js with strict TypeScript, pnpm, ESLint, and Vitest where unit tests add value.
- WebSocket for incident and device-status updates.
- Docker Compose for PostgreSQL and local development dependencies.

Versions are pinned or bounded in repository manifests and updated deliberately. Normal unit tests must not need root access, network access, or privileged host inspection.

## Core Components

### Endpoint Agent

The agent owns device identity, collection scheduling, normalization, delivery, retry, local buffering, and operational logging. Collectors implement small lifecycle and collection interfaces, and Linux-specific behavior remains isolated from shared orchestration. Permission failures produce safe diagnostic events or logs rather than crashes.

The sender uses bounded retries with backoff and a bounded durable local queue so temporary API outages do not cause unbounded memory growth or silent data loss. Collection intervals are configurable and expensive observations run less frequently than cheap observations.

### Telemetry API

The API validates an authenticated device and a versioned event envelope before persistence. Typed event payload models cover supported event types. Unknown versions, malformed payloads, invalid timestamps, and oversized requests are rejected explicitly.

Initial transport is batched HTTPS ingestion. Local development may use HTTP inside the developer-controlled environment. The server assigns or verifies idempotency identifiers so retries do not create duplicate events.

### Detection Engine

Rules are deterministic, named, versionable, configurable, and independently testable. A rule produces a detection with a score contribution, severity, evidence references, and an explanation. Risk score aggregation is centralized and clamped to 0-100. A detection is a signal, not a malware verdict.

### Correlation and Incidents

Correlation groups detections using device, process identity, executable, parent process, destination, event relationships, and bounded time windows. It begins with deterministic policies and creates one timeline for related behavior. Correlation decisions retain evidence links and rule explanations so incident construction is auditable.

### AI Investigator

An `AIProvider` interface isolates providers. The default mock provider works without credentials. Real providers are optional and configured only through environment variables.

AI receives a size-bounded, curated incident evidence bundle. Structured output separates summary, risk interpretation, hypotheses, evidence, uncertainty, and recommended next steps. Important claims reference event or detection IDs. AI has no process-control, filesystem-write, firewall, shell, or remediation capability.

### Web UI and Notifications

The UI contains Overview, Incidents, and Incident Detail. Incident Detail prioritizes the evidence timeline, process relationships, network activity, uncertainty, and recommended investigation steps. WebSocket messages invalidate or update API-backed state; PostgreSQL remains authoritative.

Notification policy is silent for normal activity, stored-only for low severity, and user-visible for medium/high severity. Linux desktop notifications use a replaceable adapter and never execute remediation.

## Data Model

The relational core contains Device, Event, DetectionRule, Detection, Incident, IncidentEvent, and AIAnalysis. Alembic is the only production schema-evolution mechanism.

Each event has an immutable envelope containing `id`, `schema_version`, `device_id`, `timestamp`, `event_type`, `source`, `severity_hint`, `data`, and `metadata`. Event-type-specific Pydantic schemas validate `data`. Database JSON columns hold validated evolving payloads, while searchable correlation keys are promoted to indexed relational columns where needed.

Incident-event and incident-detection associations preserve the evidence graph. AI analysis belongs to a specific incident evidence revision so later evidence does not silently change the meaning of stored output.

## Main Data Flow

1. A collector observes host state and produces a typed local observation.
2. The agent normalizes it into a versioned event and places it in the delivery queue.
3. The API authenticates the device, validates the batch, and persists accepted events idempotently.
4. Applicable deterministic rules produce evidence-linked detections.
5. Correlation attaches detections and events to an existing incident or creates a new one.
6. Risk and severity are recalculated from centralized policy.
7. Incident changes are pushed to connected UI clients and may trigger a notification.
8. AI investigation runs only when requested by policy or the user and stores structured, read-only analysis.

## Error Handling and Observability

Errors are categorized as validation, authentication, dependency, collection-permission, transport, and internal failures. API responses use stable error codes without leaking secrets or stack traces. Agent delivery retries only transient failures and quarantines permanently invalid events with bounded retention.

Logs are structured, redact credentials and sensitive headers, and include correlation identifiers. Health endpoints distinguish process liveness from dependency readiness. Basic counters and timings are collected without requiring a heavyweight metrics stack.

## Security Boundaries

- Secrets exist only in environment variables or ignored local files; `.env.example` contains placeholders.
- Device authentication is required before accepting production telemetry; the exact credential lifecycle is finalized in the backend milestone before exposing ingestion beyond localhost.
- Input size, batch size, enum values, timestamps, identifiers, and payload schemas are bounded and validated.
- No production path uses arbitrary command execution or `shell=True`.
- Collectors run with least privilege and degrade gracefully when host data is unavailable.
- Validation scripts act only on the local authorized lab and use benign, reversible behaviors.
- Collected command lines and user/process data are treated as potentially sensitive and retained only as needed for the project.

## Testing and Verification

Python modules use unit tests with mocked OS adapters, API and database integration tests, migration checks, and deterministic rule/correlation fixtures. The web app uses component tests for security-critical presentation logic and an end-to-end smoke path once real incidents are available.

Safe scenario tests cover resource abuse, a new listener, download/execution-like process chains, Wi-Fi anomalies, and validation coverage. Tests assert evidence and uncertainty language, not only numeric scores. Performance checks measure agent CPU, memory, collection duration, queue growth, and ingestion throughput on representative laptop hardware.

Milestone verification commands and their results are recorded in `docs/progress.md`. A failing required check blocks milestone completion and is investigated rather than disabled.

## Documentation

The repository maintains `README.md`, `docs/architecture.md`, `docs/event-model.md`, `docs/detection-engine.md`, `docs/agent.md`, `docs/api.md`, `docs/threat-model.md`, `docs/validation.md`, and `docs/progress.md`. Documentation describes only implemented behavior; planned features are labeled clearly.

## Explicit Non-Goals

- Full Windows parity in the initial implementation.
- Kernel drivers, packet interception, antivirus scanning, or automatic remediation.
- Offensive tooling against third-party systems.
- Kubernetes, Kafka, Elasticsearch, or premature microservice decomposition.
- Machine-learning detection or correlation before deterministic behavior is verified.

## Completion Criteria

The project is complete when milestones 0-11 satisfy their definitions of done, the required controlled demonstrations are repeatable, all required checks pass from documented commands, security limitations are explicit, and a clean Fedora/Linux environment can run the documented local deployment without undocumented manual fixes.
