# Correlation Engine

Status: Milestone 5A implements one deterministic, evidence-first correlation strategy. It creates a `CorrelationCandidate`, not an incident or an attack conclusion.

Milestone 5B network transition events do not change this engine's inputs or matching semantics. `PROCESS_LISTENER_ACTIVITY` continues to consume the snapshot-safe `LISTENER_OBSERVED` Detection derived from `network.listener_observed`; opened/closed transport events currently produce no Detection and no Candidate by themselves.

## Concept boundary

```text
Event       = validated technical observation
Detection   = deterministic rule match over one Event
Correlation = evidence-supported relationship among Events and Detections
Incident    = security workflow/conclusion; not implemented
```

Correlation never calls a listener newly opened, malicious, a backdoor, or an attack. The implemented candidate has low confidence and neutral wording. Incident workflow, incident timelines, AI, notifications, UI, ransomware, brute-force, port-scan, persistence, DNS, Wi-Fi, and later detection packs remain out of scope.

## Ingestion and failure boundary

```text
validated Event -> Detection Engine -> Event + Detection flush
  -> nested correlation savepoint -> optional CorrelationCandidate
  -> outer commit
```

`TelemetryIngestionService` remains the application transaction boundary. It skips duplicate Event UUIDs before detection and correlation, flushes authoritative Event and Detection rows, then runs correlation inside `session.begin_nested()`.

If correlation succeeds, its Candidate rows join the outer commit. If strategy evaluation, correlation querying, Candidate insertion, association insertion, or savepoint release fails, only the nested savepoint is rolled back. The service logs `correlation_failed` and then commits the already valid Event and Detection evidence. The log's `triggering_event_ids` currently includes every accepted Event in the batch, including accepted Events that created no Detection. Validation, Event/Detection persistence, flush, or outer-commit failures remain authoritative ingestion failures.

There is no reconciliation worker. A correlation-only failure leaves valid evidence queryable but can leave its Candidate absent until later reconciliation is implemented or another eligible new Detection triggers evaluation.

## Implemented strategy

`ProcessListenerActivityStrategy` (`PROCESS_LISTENER_ACTIVITY`) relates `PROCESS_STARTED` and `LISTENER_OBSERVED` Detections only when their source Events:

- belong to the same device;
- have the same positive PID;
- provide a valid, timezone-aware process `started_at` value;
- put the process Event at or before the listener observation; and
- fit the configured inclusive window.

`Settings.correlation_window_seconds` is the single configuration source: default 300 seconds, bounded from 1 to 86,400. The inclusive rule is:

```text
process_event.timestamp <= listener_event.timestamp
listener_event.timestamp - process_event.timestamp <= configured window
```

For each listener, eligible process starts are grouped by canonical identity `(device_id, pid, started_at)`. A result is emitted only when exactly one distinct eligible identity remains. Two identities inside the window are ambiguous and produce no Candidate; an old PID reuse outside the window is not eligible and cannot create ambiguity. PID alone is never treated as a permanent identity. Because listener evidence does not currently include process `create_time`, confidence stays `low`.

The strategy chooses the earliest eligible listener for an identity. The deterministic key is SHA-256 of the strategy ID and canonical process identity. It can therefore create at most one Candidate per `(strategy_id, device_id, pid, started_at)`.

## Persistence, evidence, and idempotency

Alembic revision `0004_correlation_foundation` creates `correlation_candidates` with a UUID primary key, globally unique 64-character correlation key, Device FK, strategy ID, start/end timestamps, low/medium/high confidence, bounded `0..100` aggregate score, neutral reason, and creation timestamp. It also creates:

- `correlation_candidate_detections`, with Candidate/Detection foreign keys and a composite primary key;
- `correlation_candidate_events`, with Candidate/Event foreign keys and a composite primary key.

The Candidate stores relational Detection and Event evidence; it is intentionally not an Incident. Existing correlation keys are checked before insertion and the database uniqueness constraint protects retries. Once the first Candidate for an identity exists, repeated listener snapshots and duplicate retries do not append evidence, change timestamps, or increase the score. This prevents artificial chains and score inflation, but intentionally loses per-listener/repeated-snapshot timeline detail until later correlation-group lifecycle semantics exist.

The model persistence test presently verifies reverse relationships using objects still held in the same SQLAlchemy identity map; a separate-session round-trip assertion is deferred. This does not change the database constraints or integration coverage, but it is weaker ORM test evidence than a fresh-session reload.

## Score and reason semantics

Candidate score is `min(100, sum(score_contribution))` over unique Detection IDs. It is a traceable internal heuristic, not malware probability, attack confidence, or final device risk. The current pair scores 5 (`PROCESS_STARTED` contributes 0; `LISTENER_OBSERVED` contributes 5). Repeated or duplicate Detection IDs count once.

The first service persists one generic, hardcoded neutral reason for this strategy: `A listener snapshot was associated with the recently started process identity.` The strategy result type does not yet carry a reason, so future strategies require a reason contract before they can safely reuse this service path.

## Deliberate limits

- No Candidate is produced for different devices, different PIDs, listener-before-process ordering, invalid/missing `started_at`, out-of-window evidence, or ambiguous eligible identities.
- A benign Python development listener can produce at most one low-confidence, score-5 Candidate for a process incarnation. It is not labeled suspicious or malicious.
- There is no Candidate API, incident conversion, background reconciliation, timeline expansion, device-risk aggregate, AI, UI, or notification behavior.
