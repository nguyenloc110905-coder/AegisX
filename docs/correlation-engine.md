# Correlation Engine

Status: Milestone 5A implements one deterministic, evidence-first correlation strategy. It creates a `CorrelationCandidate`, not an incident or an attack conclusion.

The signal-quality hardening changes only the listener evidence input:
`PROCESS_LISTENER_ACTIVITY` consumes `LISTENER_OPENED`, derived from
`network.listener_opened`, rather than repeated snapshot observations. Eligibility, identity,
idempotency, score, confidence, persistence, and failure boundaries are unchanged. Historical
`LISTENER_OBSERVED` rows remain stored and are ignored by the current strategy.

## Concept boundary

```text
Event       = validated technical observation
Detection   = deterministic rule match over one Event
Correlation = evidence-supported relationship among Events and Detections
Incident    = separately policy-promoted security workflow; foundation implemented
```

Correlation can now state that a listener endpoint appeared between complete snapshots, but never
calls that evidence malicious, a backdoor, or an attack. The implemented Candidate has low
confidence and neutral wording. The Incident foundation is separate and has no production policy
that promotes this Candidate. AI, notifications, response execution, web/desktop UI, ransomware,
brute-force, port-scan, persistence, DNS, Wi-Fi, and later detection packs remain out of scope.

## Ingestion and failure boundary

```text
validated Event -> Detection Engine -> Event + Detection flush
  -> nested correlation savepoint -> optional CorrelationCandidate
  -> outer commit
```

`TelemetryIngestionService` remains the application transaction boundary. It skips duplicate Event UUIDs before detection and correlation, flushes authoritative Event and Detection rows, then runs correlation inside `session.begin_nested()`.

If correlation succeeds, its Candidate rows join the outer commit. If strategy evaluation, correlation querying, Candidate insertion, association insertion, or savepoint release fails, only the nested savepoint is rolled back. The service captures that outcome, commits the already valid Event and Detection evidence, and only then logs `correlation_outcome` with `outcome=failed` and `evidence_committed=true`. If the authoritative outer commit fails, it emits no claim that evidence survived. Validation, Event/Detection persistence, flush, or outer-commit failures remain authoritative ingestion failures.

Every attempted correlation logs selected `strategy_ids`, safe `device_id`, `outcome` (`candidate_created`, `no_candidate`, or `failed`), and `evidence_committed=true` after commit. Success also records `candidate_count`; failure records only the exception class as `failure_category`. Logs exclude bearer tokens, command lines, event UUID lists, metadata, raw telemetry, and exception messages/stacks that could contain payload values. Logging configuration keeps bound loggers reconfigurable instead of caching stale processors.

There is no reconciliation worker. A correlation-only failure leaves valid evidence queryable but can leave its Candidate absent until later reconciliation is implemented or another eligible new Detection triggers evaluation.

## Implemented strategy

`ProcessListenerActivityStrategy` (`PROCESS_LISTENER_ACTIVITY`) relates `PROCESS_STARTED` and `LISTENER_OPENED` Detections only when their source Events:

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

For each listener-open transition, eligible process starts are grouped by canonical identity `(device_id, pid, started_at)`. A result is emitted only when exactly one distinct eligible identity remains. Two identities inside the window are ambiguous and produce no Candidate; an old PID reuse outside the window is not eligible and cannot create ambiguity. PID alone is never treated as a permanent identity. Because listener evidence does not currently include process `create_time`, confidence stays `low`.

The strategy chooses the earliest eligible listener-open transition for an identity. The deterministic key is SHA-256 of the strategy ID and canonical process identity. It can therefore create at most one Candidate per `(strategy_id, device_id, pid, started_at)`.

## Persistence, evidence, and idempotency

Alembic revision `0004_correlation_foundation` creates `correlation_candidates` with a UUID primary key, globally unique 64-character correlation key, Device FK, strategy ID, start/end timestamps, low/medium/high confidence, bounded `0..100` aggregate score, neutral reason, and creation timestamp. It also creates:

- `correlation_candidate_detections`, with Candidate/Detection foreign keys and a composite primary key;
- `correlation_candidate_events`, with Candidate/Event foreign keys and a composite primary key.

The Candidate stores relational Detection and Event evidence; it is intentionally not an Incident. Existing correlation keys are checked before insertion and the database uniqueness constraint protects retries. Once the first Candidate for an identity exists, additional listener transitions and duplicate retries do not append evidence, change timestamps, or increase the score. This prevents artificial chains and score inflation, but intentionally loses per-listener transition timeline detail until later correlation-group lifecycle semantics exist. Repeated unchanged snapshots do not generate `LISTENER_OPENED`, so they cannot manufacture Candidates.

The model persistence test presently verifies reverse relationships using objects still held in the same SQLAlchemy identity map; a separate-session round-trip assertion is deferred. This does not change the database constraints or integration coverage, but it is weaker ORM test evidence than a fresh-session reload.

## Score and reason semantics

Candidate score is `min(100, sum(score_contribution))` over unique Detection IDs. It is a traceable internal heuristic, not malware probability, attack confidence, or final device risk. The current pair scores 5 (`PROCESS_STARTED` contributes 0; `LISTENER_OPENED` contributes 5). Repeated or duplicate Detection IDs count once.

The first service persists one generic, hardcoded neutral reason for this strategy: `A listener-open transition was associated with the recently started process identity.` The strategy result type does not yet carry a reason, so future strategies require a reason contract before they can safely reuse this service path.

## Deliberate limits

- No Candidate is produced for different devices, different PIDs, listener-before-process ordering, invalid/missing `started_at`, out-of-window evidence, or ambiguous eligible identities.
- A benign Python development listener can produce at most one low-confidence, score-5 Candidate for a process incarnation. It is not labeled suspicious or malicious and no current production policy promotes it to an Incident.
- There is no Candidate API, background reconciliation, timeline expansion, device-risk aggregate, AI, web/desktop UI, notification, or response behavior.
