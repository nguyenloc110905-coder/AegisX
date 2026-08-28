# Detection Engine Foundation Design

## Scope

This design adds the Milestone 4 detection foundation and two small rules over telemetry whose meaning is already trustworthy. It does not add correlation, incidents, AI, notifications, UI, or later detection packs.

## Pipeline

The synchronous ingestion pipeline is:

```text
validated telemetry envelope
  -> mapped Event
  -> DetectionEngine
  -> relevant DetectionRule evaluations
  -> zero or more DetectionResult values
  -> deterministic risk contributions
  -> Event and Detection rows committed in one transaction
```

The FastAPI route remains an HTTP and authentication boundary. A telemetry ingestion service owns mapping, duplicate handling, detection evaluation, persistence, and the transaction. Duplicate event UUIDs are counted but not evaluated again.

## Rule abstraction

`DetectionRule` is a typed protocol. Every rule exposes:

- stable `rule_id`
- human-readable `name` and `description`
- `category`
- `severity`
- integer `score_contribution`
- immutable set of supported `event_types`
- `evaluate(event) -> RuleMatch | None`

`RuleMatch` contains a human-readable reason and one or more evidence event UUIDs. Rules remain pure and independently testable: they do not access HTTP state, database sessions, other events, AI providers, or incident state.

## Registry and engine

`RuleRegistry` receives rule instances explicitly at application composition time and builds an event-type index. Duplicate rule IDs are rejected. `rules_for(event_type)` returns only relevant rules, so the engine contains no rule-specific branches.

`DetectionEngine.evaluate(event)` evaluates the indexed rules and converts matches into immutable `DetectionResult` values containing rule metadata, the source device and event IDs, event timestamp, reason, severity, score contribution, and evidence IDs.

Unexpected rule exceptions are not suppressed in this milestone. Ingestion fails and rolls back instead of silently storing an Event without its required detection evaluation.

## Initial rules

### PROCESS_STARTED

- Event type: `process.started`
- Category: `process`
- Severity: `informational`
- Score contribution: `0`
- Meaning: the agent observed a `(PID, create_time)` process identity that was absent from its previous persisted baseline.
- Reason: states the PID and process name without calling the process suspicious.
- Evidence: the source Event UUID.

### LISTENER_OBSERVED

- Event type: `network.listener_observed`
- Category: `network`
- Severity: `low`
- Score contribution: `5`
- Meaning: a listening socket existed in the collector snapshot.
- Reason: states protocol, local address and port, and optional PID. It never says newly opened, malicious, or malware.
- Evidence: the source Event UUID.

### HIGH_RESOURCE_USAGE

Deferred. The current single `process.resource_usage` sample does not establish sustained resource abuse, and psutil sampling history is not encoded in the event. No rule will invent that evidence.

## Risk scoring

Risk values are internal deterministic heuristics, not malware probabilities. A rule match copies its configured integer contribution into the Detection row. A small scoring function computes `min(100, sum(score_contribution))` for a supplied set of results and rejects negative contributions.

This milestone does not persist a device-level aggregate because there is no correlation/window lifecycle defining when contributions should enter or leave that aggregate. Persisted per-detection contributions are traceable and ready for later bounded aggregation.

## Persistence

Alembic revision `0003_detection_foundation` creates `detections` with:

- UUID primary key
- device foreign key with cascade delete
- source event foreign key with cascade delete
- stable rule ID
- detection timestamp
- severity
- integer score contribution constrained to `0..100`
- bounded human-readable reason
- JSON evidence event UUID list
- creation timestamp

Indexes support device/time, source event, and rule/time queries. SQLAlchemy relationships connect Device and Event to Detection. The source event ID is both the direct foreign key and the first evidence reference; the JSON list leaves the result shape ready for multi-evidence rules without adding correlation now.

## Benign interpretation

A normal Python development server represented by `network.listener_observed` produces only `LISTENER_OBSERVED`, severity `low`, contribution `5`, with neutral wording. It does not produce a malware label, high severity, or any compound conclusion.

## Testing

TDD coverage includes:

- rule metadata and matching, irrelevant, and malformed ORM Event cases
- severity, score, reason, and evidence references for every implemented rule
- registry indexing and duplicate-ID rejection
- engine zero/multiple-result behavior without rule-specific branching
- deterministic clamped scoring and negative-input rejection
- benign Python listener interpretation
- Detection model constraints and relationships
- migration graph and real PostgreSQL upgrade
- authenticated telemetry ingestion persisting Event and Detection together
- duplicate ingestion not creating duplicate Detection rows
- PostgreSQL Device/Event/Detection integration flow and cleanup
- full API and unaffected agent suites, Ruff, mypy, and Alembic current/head checks

## Explicit exclusions

No cross-event state, correlation engine, incident model, ransomware, brute-force, port-scan, persistence, DNS, Wi-Fi, AI, notifications, WebSocket, or UI behavior is part of this design.
