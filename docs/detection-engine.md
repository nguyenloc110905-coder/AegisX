# Detection Engine

Status: Milestone 4 detection foundation is implemented with two deliberately weak, explainable rules. Milestone 5A adds a separate, narrow correlation foundation; later detection packs remain unimplemented.

## Pipeline

```text
validated telemetry envelope
  -> TelemetryIngestionService maps a new Event
  -> DetectionEngine selects rules through RuleRegistry
  -> DetectionRule.evaluate(Event)
  -> zero or more DetectionResult values
  -> deterministic score contributions
  -> Event and Detection rows committed together
```

`api/telemetry.py` remains the HTTP, authentication, and batch-limit boundary. `services/telemetry_ingestion.py` owns deduplication, Event mapping, detection evaluation, transactional persistence, and the post-flush correlation savepoint. A duplicate Event UUID is counted but is not evaluated again, so retries cannot duplicate Detections or trigger correlation.

## Rule contract and registry

Every `DetectionRule` exposes a stable ID, name, description, category, severity, score contribution, supported event types, and `evaluate(event)`. A match returns a neutral human-readable reason plus evidence Event UUIDs. Rules are pure: they do not access HTTP, database sessions, AI, incidents, or other events.

`RuleRegistry` is explicitly composed in `detection/defaults.py`, rejects duplicate IDs, and indexes rules by event type. `DetectionEngine` contains no rule-specific branch.

## Implemented rules

| Rule | Evidence | Severity | Contribution | Interpretation |
|---|---|---:|---:|---|
| `PROCESS_STARTED` | `process.started` | informational | 0 | Records the agent-proven newly observed process identity. It does not label every process suspicious. |
| `LISTENER_OBSERVED` | `network.listener_observed` | low | 5 | Records that a listener existed in a snapshot. It does not claim the listener was newly opened. |

`HIGH_RESOURCE_USAGE` is deferred. The current event is one process resource sample and does not prove sustained resource abuse. Correlation is implemented separately as the limited `PROCESS_LISTENER_ACTIVITY` Candidate behavior documented in [correlation-engine.md](correlation-engine.md); it does not create Incidents. Ransomware, brute-force, port-scan, persistence, DNS, Wi-Fi, AI, incidents, notifications, and UI remain excluded.

## Risk scoring

A contribution is a deterministic internal heuristic, not a malware probability. Each Detection persists the exact contribution declared by its matching rule. `calculate_risk_score()` sums supplied Detection results and clamps the result to 100; negative contributions are rejected.

No device-level aggregate is persisted yet because a correct aggregate needs correlation and time-window expiry semantics. A legitimate Python development listener therefore creates only a low-severity contribution of 5 with neutral wording.

## Persistence and evidence

Migration `0003_detection_foundation` creates `detections`. Each row has cascading foreign keys to its Device and source Event, plus rule ID, event timestamp, severity, contribution, reason, evidence Event UUID list, and creation time. The source Event FK is authoritative direct evidence. `evidence_event_ids` preserves the rule result's evidence list for future multi-evidence rules. Correlation Candidate evidence is stored separately through relational association tables; see [correlation-engine.md](correlation-engine.md).

Event and Detection rows share the authoritative outer transaction. A rule exception rolls the request back instead of silently storing telemetry that skipped required evaluation. Correlation runs only after those rows flush, in a nested savepoint: a correlation-only failure is logged and rolled back to that savepoint while valid Event/Detection evidence still commits.
