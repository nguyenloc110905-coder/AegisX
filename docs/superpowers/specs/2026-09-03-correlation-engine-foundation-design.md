# Correlation Engine Foundation Design

## Scope

Milestone 5A adds a deterministic, evidence-first correlation layer over persisted Events and Detections. Correlation answers which technical observations are sufficiently related to form a candidate. It does not decide that an attack occurred and does not create an Incident.

This milestone excludes incident workflow, AI, notifications, UI, ransomware, brute-force, port-scan, persistence, DNS, Wi-Fi, and other advanced detection packs.

## Pipeline

```text
validated Event
  -> Detection Engine
  -> Detection
  -> flush authoritative Event and Detection evidence
  -> correlation savepoint
       -> Correlation Engine
       -> ProcessActivityCorrelationStrategy
       -> optional CorrelationCandidate
  -> commit authoritative Event and Detection transaction
```

`TelemetryIngestionService` remains the transactional application boundary. It maps and evaluates each new Event, flushes new Event and Detection rows so their identifiers are available, and then opens a nested transaction/savepoint for correlation. Successful correlation releases the savepoint so Candidate rows participate in the outer commit. A correlation exception rolls back only the savepoint; the service records the correlation failure and commits the already valid Event and Detection evidence in the outer transaction. Duplicate Event UUIDs are skipped before detection and correlation.

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
- exactly one distinct eligible process identity remains after applying the conflict rule below.

For a specific listener observation, a `PROCESS_STARTED` Detection belongs to the eligible set only when all of these conditions hold:

- it has the same device ID as the listener Detection;
- its source Event has the same positive PID as the listener source Event;
- its source Event timestamp is less than or equal to the listener source Event timestamp;
- the difference between listener timestamp and process timestamp is less than or equal to the configured correlation window;
- its source Event contains a valid `started_at` value.

Eligible process-start evidence is grouped by the canonical process identity `(device_id, pid, started_at)`. Correlation is ambiguous only when more than one distinct canonical process identity remains inside that eligible set. Process starts outside the configured window are not eligible and therefore cannot create a conflict, including old PID reuse outside the window.

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

The deterministic key is a SHA-256 digest over strategy ID and canonical process identity. A unique database constraint makes retries and repeated listener snapshots idempotent. The initial strategy persists at most one Candidate for each `(strategy_id, device_id, pid, started_at)` tuple. Once that Candidate exists, every additional listener or listener snapshot for the same process incarnation is intentionally ignored: Milestone 5A does not append its Detection/Event evidence and does not increase the Candidate score.

This choice prevents artificial activity chains and risk inflation, but it deliberately loses per-listener and repeated-snapshot timeline detail. That loss is a known foundation limitation and must be revisited when correlation-group lifecycle and timeline semantics are designed in a later milestone.

## Risk semantics

Candidate score is `min(100, sum(score_contribution))` across unique related Detection IDs. It is a traceable internal heuristic, not malware probability, attack confidence, or final device risk. Repeated or duplicate Detection IDs contribute once.

The first pair currently yields 5: `PROCESS_STARTED` contributes 0 and `LISTENER_OBSERVED` contributes 5. Confidence remains `low` regardless of this numeric contribution because listener process create time is unavailable.

## Service integration

`CorrelationService` owns the database query and Candidate persistence boundary. It loads only relevant recent Detections for the same device and configured time horizon, including their source Events; passes complete evidence to `CorrelationEngine`; checks existing deterministic keys; and adds only new Candidates with their association rows inside the caller-owned correlation savepoint.

The HTTP route remains unchanged. Detection rules remain unaware of correlation. Correlation strategies do not commit transactions or call HTTP services.

Correlation failure is non-authoritative and must not fail valid telemetry ingestion. `TelemetryIngestionService` flushes Event and Detection evidence before entering `session.begin_nested()`. If strategy evaluation, correlation querying, Candidate insertion, association insertion, or correlation-savepoint release fails, the nested transaction is rolled back, a structured error is logged with the device and triggering Event IDs, and no partial Candidate or association rows survive. The outer transaction then commits the valid Event and Detection rows and the ingestion response reports them as accepted.

Only failure of Event/Detection validation, persistence, flush, or the outer commit fails ingestion and rolls back authoritative evidence. Milestone 5A does not implement a background reconciliation worker: after a correlation-only failure, the evidence remains queryable but its missing Candidate requires a later explicit reconciliation capability or another eligible new Detection to trigger evaluation. This is documented technical debt rather than a reason to discard evidence.

## False-correlation protection

Tests must prove no Candidate is produced for:

- different devices;
- different PIDs;
- timestamps outside the configured window;
- listener observations before process-start evidence;
- invalid or missing process `started_at`;
- multiple distinct `(device_id, pid, started_at)` identities remaining in the precisely bounded eligible process-start set;
- duplicate Detection evidence;
- repeated listener snapshots for an already persisted process-identity Candidate.

A benign Python development server produces at most one low-confidence, score-5 process/listener activity Candidate per `(strategy_id, device_id, pid, started_at)`, with neutral language. Additional listeners and snapshots for that process incarnation are not appended in Milestone 5A.

## Verification

TDD coverage includes strategy match and non-match behavior, precisely bounded conflicting-identity behavior, old PID reuse outside the window, registry/engine dispatch, centralized window configuration, score deduplication, deterministic keys, persistence relationships and constraints, savepoint-isolated correlation failure with surviving Event/Detection evidence, ingestion integration, retry/repeated-snapshot idempotency, one-Candidate-per-process-identity behavior, known timeline-detail omission, benign interpretation, Alembic graph checks, and a real PostgreSQL Event/Detection/Candidate flow.

Final verification runs the complete API and agent suites, Ruff formatting and lint, strict mypy, PostgreSQL integration, Alembic upgrade/current/heads, and Git whitespace checks.

## Concept boundaries

```text
Event       = validated technical observation
Detection   = deterministic rule match over an Event
Correlation = evidence-supported relationship between observations
Incident    = security workflow/conclusion; not implemented
```
