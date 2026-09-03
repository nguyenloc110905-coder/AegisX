# Correlation Engine Foundation Design

## Scope

Milestone 5A adds a deterministic, evidence-first correlation layer over persisted Events and Detections. Correlation answers which technical observations are sufficiently related to form a candidate. It does not decide that an attack occurred and does not create an Incident.

This milestone excludes incident workflow, AI, notifications, UI, ransomware, brute-force, port-scan, persistence, DNS, Wi-Fi, and other advanced detection packs.

## Pipeline

```text
validated Event
  -> Detection Engine
  -> Detection
  -> Correlation Engine
  -> ProcessActivityCorrelationStrategy
  -> CorrelationCandidate
  -> Event, Detection, and Candidate commit in one transaction
```

`TelemetryIngestionService` remains the transactional application boundary. It maps and evaluates each new Event, flushes new Event and Detection rows so their identifiers are available, asks the correlation service to compare new evidence with bounded persisted history, and commits all new rows together. Duplicate Event UUIDs are skipped before detection and correlation.

## Correlation abstraction

`CorrelationStrategy` is a typed protocol. Each strategy declares a stable ID, name, description, required detection rule IDs, and an `evaluate(evidence, window)` method. It is independently testable and contains only one correlation behavior.

`CorrelationEngine` receives explicitly registered strategies. It indexes them by relevant rule ID and invokes only strategies affected by new Detections. The engine contains no strategy-specific branches.

`CorrelationResult` is immutable and contains:

- deterministic correlation key
- device ID
- strategy ID
- start and end timestamps
- low-confidence, human-readable reason
- heuristic aggregate score
- unique Detection evidence UUIDs
- unique Event evidence UUIDs

## First strategy: process activity with observed listener

`ProcessListenerActivityStrategy` considers one `PROCESS_STARTED` Detection and one `LISTENER_OBSERVED` Detection related only when all available evidence supports the relationship:

- both Detections belong to the same device;
- both source Events contain the same positive PID;
- the process Event contains a valid `started_at` timestamp;
- the process Event timestamp is not later than the listener observation;
- the listener observation occurs within the configured window after the process Event;
- no conflicting eligible `PROCESS_STARTED` evidence for the same device/PID but a different `started_at` makes the identity ambiguous.

The process identity key is `(device_id, pid, started_at)`. PID alone is never used as permanent identity. The listener event does not currently carry process `create_time`, so the candidate remains low-confidence and its reason says only that a listener snapshot was associated with the recently started process identity. It never says newly opened, backdoor, malicious, or attack.

When evidence is incomplete, malformed, conflicting, on different devices, outside the window, or otherwise ambiguous, the strategy returns no result.

## Time-window semantics

`Settings.correlation_window_seconds` is the single configuration source, defaulting to 300 seconds with validated bounds from 1 to 86,400 seconds. The window is a heuristic to bound candidate activity, not a scientific threshold. Later validation will calibrate it.

The inclusive rule is:

```text
process_event.timestamp <= listener_event.timestamp
listener_event.timestamp - process_event.timestamp <= configured window
```

No strategy hardcodes its own duration.

## Persistence and idempotency

Persistence is justified because an in-memory candidate currently has no API response or downstream consumer and would disappear after ingestion.

Alembic revision `0004_correlation_foundation` creates:

### `correlation_candidates`

- UUID primary key
- unique deterministic `correlation_key`
- Device foreign key with cascade delete
- strategy ID
- start/end timestamps
- confidence fixed to the bounded correlation vocabulary
- aggregate heuristic score constrained to `0..100`
- bounded neutral reason
- creation timestamp

### Evidence association tables

- `correlation_candidate_detections`: candidate and Detection foreign keys with a composite primary key
- `correlation_candidate_events`: candidate and Event foreign keys with a composite primary key

The associations preserve relational evidence integrity. The Candidate is explicitly not named or modeled as an Incident.

The deterministic key is a SHA-256 digest over strategy ID and canonical process identity. A unique database constraint makes retries and repeated listener snapshots idempotent. Once a Candidate exists for a process identity, later snapshots do not append evidence or increase its score; this prevents artificial activity chains and risk inflation.

## Risk semantics

Candidate score is `min(100, sum(score_contribution))` across unique related Detection IDs. It is a traceable internal heuristic, not malware probability, attack confidence, or final device risk. Repeated or duplicate Detection IDs contribute once.

The first pair currently yields 5: `PROCESS_STARTED` contributes 0 and `LISTENER_OBSERVED` contributes 5. Confidence remains `low` regardless of this numeric contribution because listener process create time is unavailable.

## Service integration

`CorrelationService` owns the database query and persistence boundary. It loads only relevant recent Detections for the same device and configured time horizon, including their source Events; passes complete evidence to `CorrelationEngine`; checks existing deterministic keys; and adds only new Candidates with their association rows.

The HTTP route remains unchanged. Detection rules remain unaware of correlation. Correlation strategies do not commit transactions or call HTTP services.

Any unexpected correlation error aborts ingestion and rolls back Event, Detection, and Candidate work together. The system does not silently persist partially evaluated security data.

## False-correlation protection

Tests must prove no Candidate is produced for:

- different devices;
- different PIDs;
- timestamps outside the configured window;
- listener observations before process-start evidence;
- invalid or missing process `started_at`;
- conflicting process starts with the same PID and different `started_at`;
- duplicate Detection evidence;
- repeated listener snapshots for an already persisted process-identity Candidate.

A benign Python development server produces at most one low-confidence, score-5 process/listener activity Candidate with neutral language.

## Verification

TDD coverage includes strategy match and non-match behavior, registry/engine dispatch, centralized window configuration, score deduplication, deterministic keys, persistence relationships and constraints, ingestion integration, retry/repeated-snapshot idempotency, benign interpretation, Alembic graph checks, and a real PostgreSQL Event/Detection/Candidate flow.

Final verification runs the complete API and agent suites, Ruff formatting and lint, strict mypy, PostgreSQL integration, Alembic upgrade/current/heads, and Git whitespace checks.

## Concept boundaries

```text
Event       = validated technical observation
Detection   = deterministic rule match over an Event
Correlation = evidence-supported relationship between observations
Incident    = security workflow/conclusion; not implemented
```
