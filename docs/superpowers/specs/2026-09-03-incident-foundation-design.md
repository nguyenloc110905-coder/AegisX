# Milestone 6A — Incident Foundation Design

Status: proposed for review. This document defines architecture and semantics only. It does not authorize or implement Incident source code, APIs, AI, UI, notifications, response actions, or new attack-detection packs.

## 1. Purpose and concept boundary

An Incident is a durable triage case that groups deterministic, evidence-supported security behavior for lifecycle management. It is not raw telemetry, a rule match, a relationship hypothesis, a malware verdict, or threat attribution.

| Object | Meaning | May claim |
|---|---|---|
| `Event` | Validated technical observation from a collector. | Only what the collector proved, using the Event timestamp as observation time unless the payload proves a stronger timestamp. |
| `Detection` | Deterministic rule match over one Event. | The named behavior recognized by that rule, its reason, severity, and heuristic score contribution. |
| `CorrelationCandidate` | Deterministic relationship among persisted Detections/Events. | The strategy-defined relationship, confidence, time bounds, and deduplicated aggregate score. It is still a candidate, not a case or attack conclusion. |
| `Incident` | Operational case created from one or more eligible CorrelationCandidates under an explicit promotion policy. | That the related behavior merits human triage at a stated risk/severity/confidence. It must not claim malware, actor, campaign, intent, or attack family without separate human-confirmed evidence. |

The foundation pipeline is:

```text
Event -> Detection -> CorrelationCandidate
      -> IncidentPromotionPolicy -> IncidentDecision
      -> Incident create/attach -> Incident evidence + status history
```

The Incident layer never reinterprets raw telemetry and never performs AI reasoning.

## 2. Promotion architecture

Promotion is modular. There is no giant conditional in ingestion.

An `IncidentPromotionPolicy` has:

- stable `policy_id` and positive integer `policy_version`;
- supported `CorrelationCandidate.strategy_id` values;
- name and human-readable behavior description;
- deterministic `evaluate(candidate) -> IncidentDecision | None`;
- deterministic grouping-key construction;
- optional thresholds stricter than the global floor, but never weaker;
- deterministic title and promotion reason templates.

An `IncidentPolicyRegistry` rejects duplicate `(policy_id, policy_version)` registrations and indexes policies by candidate strategy ID. A candidate is not eligible merely because a policy class exists: `evaluate` must return a complete `IncidentDecision`.

`IncidentDecision` contains:

- `policy_id` and `policy_version`;
- a stable 64-character SHA-256 `grouping_key` derived only from canonical, non-secret evidence identity;
- deterministic title and behavior summary;
- the effective score and confidence thresholds used;
- the candidate ID selected as the trigger.

### Initial production registry

Milestone 6A registers no auto-promotion policy for `PROCESS_LISTENER_ACTIVITY`. That Candidate is low confidence with aggregate score 5 and can describe a benign Python development listener. It therefore creates and contributes to no Incident.

Policy engine behavior must be tested with explicit test-only policies and test fixtures. Milestone 6A must NOT introduce a production promotion policy merely to make Incident creation tests pass. Incident creation tests should use a test-only policy until a real production correlation strategy satisfies all promotion requirements. Enabling a production policy is a separate semantic decision and must not be smuggled into the foundation implementation.

## 3. Exact candidate eligibility gates

A persisted CorrelationCandidate may create or contribute to an Incident only when every condition below is true:

1. Exactly one active, versioned `IncidentPromotionPolicy` is registered for its `strategy_id`; zero policies means ineligible, and multiple matching policies is a configuration error that produces no Incident.
2. The policy returns a non-null deterministic `IncidentDecision` for that Candidate.
3. The Candidate confidence is at least `medium`. Confidence ordering is `low < medium < high`.
4. The Candidate `aggregate_score` is at least 30. A policy may require a higher score or confidence but cannot lower these global floors.
5. The Candidate has valid bounds: timezone-aware `start_timestamp <= end_timestamp`.
6. It references at least one persisted Detection and one persisted Event.
7. The Candidate, every referenced Detection, and every referenced Event belong to the same Device.
8. Every referenced Detection's source Event is present in the Candidate's Event evidence set. Extra Candidate Event evidence is allowed only when the correlation strategy intentionally referenced it.
9. The Candidate is not already linked to any Incident. Reprocessing a Candidate already linked to an Incident is an idempotent `already_attached` success and performs no evaluation or mutation.
10. Its policy decision contains a valid grouping key, title, summary, and threshold snapshot.

Malformed, cross-device, incomplete, ambiguous-policy, or already-attached candidates fail closed: they create nothing, mutate nothing, and produce a bounded diagnostic outcome.

The global foundation floors are design constants, not claims of statistical validity. If made configurable during implementation, validated defaults must be `incident_min_score=30` and `incident_min_confidence=medium`, and the effective values must be persisted on the Incident so later configuration changes cannot rewrite history.

## 4. Create versus contribute rules

For an eligible Candidate, the service first serializes work for the canonical `(device_id, policy_id, policy_version, grouping_key)` using a PostgreSQL transaction-scoped advisory lock, then looks for attachable Incidents with the same:

- `device_id`;
- `policy_id` and `policy_version`;
- `grouping_key`;
- active lifecycle state.

An Incident is active for evidence attachment only when its status is `OPEN` or `INVESTIGATING` AND its disposition is `UNDETERMINED`. If a human operator sets a definitive disposition (e.g., `CONFIRMED_THREAT`, `BENIGN`, `FALSE_POSITIVE`), the Incident is frozen for automatic evidence attachment because that is a human conclusion. The `RESOLVED` status is also strictly frozen.

The Candidate contributes to the matching Incident only when its interval is within the evidence session window:

```text
candidate.start_timestamp <= incident.last_evidence_at + window
AND
candidate.end_timestamp >= incident.first_evidence_at - window
```

Eligibility strictly uses the Candidate's timezone-aware telemetry timestamps (`start_timestamp` and `end_timestamp`), never the ingestion wall-clock time. This ensures that delayed or out-of-order telemetry evaluates deterministically. The default inclusive window is 3,600 seconds and is validated as `incident_evidence_window_seconds` with range 1–86,400. One hour is a conservative sessionization interval above the current five-minute correlation window; it groups nearby candidate behavior without claiming long-running campaign correlation. Persist the effective window on creation.

Exactly one matching in-window Incident is required for attachment. If more than one qualifies, the state is ambiguous and the system fails closed: the service attaches to none, creates none, rolls back the Incident savepoint, and records a bounded diagnostic outcome. It does not guess, merge, or select the newest Incident.

When attached, the Incident updates `first_evidence_at = min(incident.first_evidence_at, candidate.start_timestamp)` and `last_evidence_at = max(incident.last_evidence_at, candidate.end_timestamp)`. Importantly, `last_evidence_at` must never move backward, and late-arriving historical evidence cannot retroactively bridge a gap to accidentally merge two temporally separate episodes that were already processed. It recomputes risk/severity/confidence, updates `updated_at`, and increments the optimistic `version` in the same savepoint. This is a sliding session: a chain of eligible candidates with no gap larger than the configured window may keep an `OPEN`/`INVESTIGATING` Incident active. Automatic attachment never changes Incident status or disposition.

If no in-window attachable Incident exists, the eligible Candidate creates a new `OPEN` Incident even when an older `OPEN`/`INVESTIGATING` Incident with the same group exists outside the window. This explicitly means multiple `OPEN` or `INVESTIGATING` Incidents for the exact same grouping key can and will exist concurrently if they represent temporally distinct episodes. A Candidate matching only frozen or terminal Incidents likewise creates a new Incident if it is not already attached elsewhere and still passes all eligibility gates.

One Incident may contain multiple CorrelationCandidates. One CorrelationCandidate may belong to at most one Incident in Milestone 6A. Incident merge, split, candidate reassignment, and cross-device grouping are excluded.

## 5. Incident lifecycle

To avoid conflating workflow state with security outcome, the Incident lifecycle is separated into `status` and `disposition`. All values are uppercase.

Statuses (workflow):
- `OPEN`: created deterministically and waiting for triage.
- `INVESTIGATING`: a human operator has begun review.
- `RESOLVED`: investigation or remediation is complete.

Dispositions (security outcome):
- `UNDETERMINED`: default state while open or investigating.
- `BENIGN`: authorized administrative or legitimate behavior.
- `FALSE_POSITIVE`: a detection or correlation error; the behavior did not actually occur or was misinterpreted.
- `CONFIRMED_THREAT`: a human operator confirmed a real security threat. (This is a disposition, not threat actor/campaign attribution.)

Allowed status transitions are:

```text
SYSTEM creation -> OPEN
OPEN -> INVESTIGATING | RESOLVED
INVESTIGATING -> RESOLVED
```

Dispositions can be updated at any time by an authorized operator, but moving to `RESOLVED` status requires a non-`UNDETERMINED` disposition. `RESOLVED` is terminal in 6A. All other status transitions are rejected, including transitions to the current status. Reopening is deferred because its evidence and notification semantics are not yet designed. New eligible evidence never automatically changes status, resolves a case, or reverses a human disposition.

Every non-creation transition requires:

- expected current row `version` for optimistic concurrency;
- `actor_type=operator`;
- non-empty opaque `actor_id`;
- non-empty human reason;
- one append-only status-history record.

Milestone 6A has no authenticated operator identity or status API. The domain state machine and persistence contract may be implemented and tested internally, but exposing operator transitions must wait for a reviewed authentication/authorization boundary.

## 6. Observation, assessment, risk, confidence, and attribution

These concepts are deliberately independent:

### Confirmed observations

Events remain the facts. An Incident does not copy or strengthen their claims. For example, `network.listener_observed` proves snapshot presence; `network.listener_opened` proves an endpoint-presence transition between complete snapshots; neither proves malicious intent.

### Behavior assessment

Detection reasons, CorrelationCandidate reasons, and the promotion policy summary describe deterministic behavior. The Incident title and summary are operational language derived from the policy. They must avoid malware/attack wording unless the supporting reviewed policy can prove that behavior.

### Risk

`risk_score` is an integer heuristic from 0 through 100, not a probability. It is recomputed from the union of unique Detection IDs reachable through all attached Candidates:

```text
risk_score = min(100, sum(unique Detection.score_contribution))
```

The unique-ID union prevents repeated Candidates or overlapping evidence from double-counting the same Detection. Persist `risk_score` and `risk_calculation_version=1`; every attached Candidate must leave a traceable path to every contribution.

### Severity

Incident severity is operational priority derived from the persisted risk score in version 1:

| Risk | Severity |
|---:|---|
| 0–9 | `informational` |
| 10–29 | `low` |
| 30–59 | `medium` |
| 60–79 | `high` |
| 80–100 | `critical` |

Severity does not confirm maliciousness. Attaching evidence may increase severity; status changes do not modify it.

### Confidence

Confidence is categorical evidence support, not probability. Incident confidence is the maximum of attached eligible Candidate confidences under ordering `low < medium < high`. Because every attached Candidate must meet the medium global floor, an automatically created Incident is never `low`. A weaker future Candidate cannot reduce previously established support, and repeated evidence cannot inflate confidence beyond its strongest Candidate.

### Threat attribution

No threat actor, malware family, campaign, intent, ATT&CK technique conclusion, or attribution score is generated in 6A. `CONFIRMED_THREAT` is an operator disposition only. Any future attribution is a separate, sourced object and must not overwrite observations, behavior assessment, risk, or confidence.

## 7. Evidence references and persistence model

Milestone 6A proposes Alembic migration `0005_incident_foundation`.

### `incidents`

- `id UUID PRIMARY KEY`;
- `incident_key VARCHAR(64) NOT NULL UNIQUE`;
- `device_id UUID NOT NULL` FK to `devices.id`;
- `policy_id VARCHAR(128) NOT NULL`;
- `policy_version INTEGER NOT NULL` and positive;
- `grouping_key VARCHAR(64) NOT NULL`;
- `title VARCHAR(256) NOT NULL`;
- `summary VARCHAR(2048) NOT NULL`;
- `status VARCHAR(32) NOT NULL` with the three allowed values;
- `disposition VARCHAR(32) NOT NULL DEFAULT 'UNDETERMINED'` with the four allowed values;
- `severity VARCHAR(16) NOT NULL` with the five allowed values;
- `risk_score INTEGER NOT NULL` constrained 0–100;
- `risk_calculation_version INTEGER NOT NULL DEFAULT 1`;
- `confidence VARCHAR(16) NOT NULL` constrained to `medium` or `high` for auto-created Incidents;
- `promotion_score_threshold INTEGER NOT NULL` constrained 0–100;
- `promotion_confidence_threshold VARCHAR(16) NOT NULL`;
- `evidence_window_seconds INTEGER NOT NULL` constrained 1–86,400;
- `first_evidence_at TIMESTAMPTZ NOT NULL`;
- `last_evidence_at TIMESTAMPTZ NOT NULL`, constrained not before first evidence;
- `version INTEGER NOT NULL DEFAULT 1` and positive;
- `closed_at TIMESTAMPTZ NULL`, required only for `RESOLVED`;
- `created_at` and `updated_at` as timezone-aware server timestamps.

Indexes support `(device_id, status, last_evidence_at)`, `(policy_id, status, last_evidence_at)`, and `(device_id, policy_id, policy_version, grouping_key, last_evidence_at)`. There is intentionally no unique constraint over an active group: two separate time-window episodes may both remain `OPEN` or `INVESTIGATING`. Transaction-scoped group locking and the deterministic in-window query prevent duplicate same-episode creation during normal writes.

`incident_key` is SHA-256 over `policy_id | policy_version | device_id | grouping_key | seed_candidate_id`. Retrying creation from the same seed produces the same key. A later episode after a terminal/frozen Incident uses its new seed Candidate and gets a distinct key.

### Evidence association tables

- `incident_correlation_candidates(incident_id, candidate_id)`: composite primary key; `candidate_id` is additionally unique, enforcing at most one Incident per Candidate.
- `incident_detections(incident_id, detection_id)`: composite primary key.
- `incident_events(incident_id, event_id)`: composite primary key.

When attaching a Candidate, the service inserts the Candidate link and the union of its Detection/Event links. Duplicate association rows are ignored by key, not appended. Explicit Detection/Event links make evidence queries and timeline construction direct; they are snapshots of the immutable Candidate evidence graph and must be validated against that graph before insertion.

Foreign keys cascade association-row deletion when an owning Incident or underlying evidence row is deleted, consistent with the repository's existing Device evidence cascade. Milestone 6A adds no evidence-deletion API or retention policy.

### `incident_status_transitions`

- `id UUID PRIMARY KEY`;
- `incident_id UUID NOT NULL` FK;
- nullable `from_status` and `from_disposition` only for the creation record;
- `to_status VARCHAR(32) NOT NULL`;
- `to_disposition VARCHAR(32) NOT NULL`;
- `actor_type VARCHAR(16) NOT NULL` constrained to `system` or `operator`;
- `actor_id VARCHAR(256) NULL`, null only for system creation;
- `reason VARCHAR(2048) NOT NULL`;
- `occurred_at TIMESTAMPTZ NOT NULL`;
- `incident_version INTEGER NOT NULL` and positive.

Index `(incident_id, occurred_at, id)` supports deterministic history. Status history is append-only.

## 8. Idempotency and concurrency

Idempotency is enforced at several layers:

1. Existing Event UUID deduplication prevents duplicate Detection/Correlation work during normal ingestion retry.
2. Existing CorrelationCandidate `correlation_key` uniqueness prevents repeated Candidate persistence.
3. Unique `incident_correlation_candidates.candidate_id` makes reprocessing one Candidate a no-op after its first successful attachment.
4. Deterministic `incident_key` protects repeated creation from the same seed.
5. A PostgreSQL transaction-scoped advisory lock serializes concurrent promotion. The 64-character SHA-256 `grouping_key` is deterministically mapped to a 64-bit integer lock key (e.g., by parsing the first 16 hex characters). Hash collisions in this 64-bit space may briefly serialize unrelated groups, but they do not cause Incident identity collisions because the full string `grouping_key` is strictly verified during the in-window query. Lock acquisition must use a precise bounded timeout (e.g., waiting no more than 2.0 seconds) rather than waiting indefinitely.
6. Evidence association composite keys prevent duplicate Event/Detection links and risk inflation.
7. Status mutation uses optimistic `version`; stale concurrent transitions fail rather than overwrite each other.

For two concurrent eligible Candidates in the same group, the transaction-scoped advisory lock serializes their Incident processing. The first transaction acquires the lock, observes no in-window Incident, creates a new one, and commits. The second transaction waits for the lock; upon acquiring it, it correctly observes the newly committed in-window Incident and attaches to it. If lock acquisition times out or any other promotion error occurs, it fails closed: it rolls back only its Incident savepoint, defers without guessing, and records a bounded failure outcome.

## 9. What must not automatically create an Incident

The following never auto-create an Incident in 6A:

- an Event by itself;
- a Detection by itself;
- raw score or severity without a registered promotion policy;
- `process.started`, `process.exited`, or resource usage alone;
- `network.listener_observed`, `network.connection_observed`, or any opened/closed transition alone;
- `PROCESS_STARTED`, `LISTENER_OBSERVED`, or their benign combination alone;
- the current low-confidence, score-5 `PROCESS_LISTENER_ACTIVITY` Candidate;
- repeated listener snapshots or duplicate Event/Candidate retries;
- malformed, cross-device, ambiguous, incomplete, or evidence-less Candidates;
- a correlation or Incident-processing failure;
- an AI suggestion, future notification, UI action without authorization, or response-action result;
- a human label unless it passes the explicit status-transition authorization boundary.

## 10. Transaction and failure behavior

The ingestion boundary remains evidence-first:

```text
outer ingestion transaction
  persist/flush Event + Detection                   authoritative
  correlation savepoint -> optional Candidate      derived
  incident savepoint -> optional Incident/evidence derived workflow
outer commit
post-commit bounded outcome logging
```

Incident evaluation, locking, query, insertion, association, risk recomputation, timeline/status-history creation, or savepoint release failure rolls back only the Incident savepoint. Authoritative Event and Detection evidence, as well as any successfully created CorrelationCandidate from the preceding correlation savepoint, remain completely unaffected. The strict ordering is: Event persistence ✅ -> Detection persistence ✅ -> Correlation savepoint release (Candidate ✅) -> Incident savepoint (Incident ❌ upon failure). A failure in higher-order workflow layers never causes validated telemetry or relationship evidence to be lost.

Only validation, Event/Detection persistence, their flush, or the outer commit itself is an authoritative ingestion failure. No log may claim `evidence_committed=true` before that outer commit succeeds. Incident logs contain policy/strategy IDs, safe Device ID, Candidate ID if needed for diagnosis, outcome, failure category, and post-commit evidence/Candidate commit flags; they exclude tokens, command lines, raw telemetry, metadata, and payload-bearing exception messages/stacks.

There is no reconciliation worker in 6A. If Incident processing fails after a Candidate is produced, that Candidate remains unattached and queryable, but automatic retry may not occur until a future reconciliation mechanism is explicitly designed. This is a known operational limitation, not permission to roll back evidence.

## 11. Human-readable timeline

The Incident timeline is a deterministic read model, not another source of truth. It is constructed from persisted Incident evidence and status history:

- Event entry at `Event.timestamp`: concise event-type-specific observation text; no stronger claim than the Event semantics.
- Detection entry at `Detection.timestamp`: rule ID, severity, score contribution, and persisted reason.
- Correlation entry at Candidate `end_timestamp`: strategy ID, interval, confidence, aggregate score, and persisted reason.
- Lifecycle entry at transition `occurred_at`: old/new status, actor type/ID where authorized, and reason.

Entries sort by `(occurred_at, kind_order, stable_id)`, where kind order is `event`, `detection`, `correlation`, `status`. Each entry includes stable source type and source ID so the reader can inspect the underlying record. Repeated references are deduplicated by `(source_type, source_id)`.

Timeline presentation uses bounded summaries and promoted fields by default. It does not expose bearer tokens and does not automatically display full command lines, arbitrary metadata, or raw JSON telemetry. Redaction and field-level authorization require a later API/security design.

No denormalized timeline rows are persisted in 6A. This avoids drift; future UI pagination may add a materialized read model without changing evidence ownership.

## 12. Future compatibility without implementation

- **AI Investigator:** consumes a read-only Incident snapshot, timeline, and cited evidence IDs. AI output must live in a separate versioned analysis record, label uncertainty, cite sources, and never mutate status/risk/evidence automatically.
- **Notifications:** react only to committed Incident/status changes through a future transactional outbox. No notification network call occurs inside ingestion or Incident transactions.
- **Response actions:** use separate requested/approved/executed audit records, explicit authorization, idempotency keys, and evidence links. Incident status alone never executes an endpoint action.
- **UI/API:** use Incident list/detail/timeline read models, optimistic `version` for status mutation, server-side authorization, pagination, and bounded/redacted evidence. No UI-specific fields or route contracts are required in the core model.

These are compatibility seams only. Milestone 6A must not add providers, prompts, WebSockets, frontend code, notification adapters, command execution, or response-action APIs.

## 13. Required tests

### Policy and decision tests

- registry selection by strategy ID and rejection of duplicate policy identity;
- no policy, null decision, multiple-policy ambiguity, malformed decision, cross-device evidence, missing evidence, and invalid timestamps all produce no Incident;
- exact global boundaries: score 29 rejected, score 30 accepted; low confidence rejected, medium/high accepted;
- stricter policy thresholds apply and effective thresholds persist;
- the production registry does not promote `PROCESS_LISTENER_ACTIVITY`.

### Benign and false-positive tests

- a legitimate Python development server represented by `PROCESS_STARTED` plus `LISTENER_OBSERVED` and the current score-5/low Candidate creates no Incident;
- repeated listener snapshots and duplicate Candidate processing create no extra Incident/evidence/risk;
- setting disposition to `FALSE_POSITIVE` preserves all evidence and adds only an audited transition history record;
- an Incident with a non-`UNDETERMINED` disposition cannot receive automatic evidence.

### Grouping, window, and scoring tests

- first eligible Candidate creates one `OPEN` Incident;
- second eligible Candidate with same device/policy/group inside the inclusive window attaches to the same Incident;
- different device, grouping key, policy version, or outside-window Candidate creates a distinct Incident;
- one Incident supports multiple Candidates while one Candidate cannot attach to two Incidents;
- overlapping Candidate evidence counts each Detection contribution once;
- risk clamps at 100, severity boundaries match the table, and confidence uses maximum eligible Candidate confidence;
- evidence bounds expand deterministically for late but in-window Candidates;
- frozen/terminal Incident receives no automatic attachment; a new eligible episode may create a new Incident.

### Lifecycle and timeline tests

- every allowed status edge succeeds with expected version, operator identity, reason, timestamps, `closed_at`, and history;
- every forbidden edge, self-transition, missing actor/reason, and stale version fails without mutation;
- only system creation may have null actor ID;
- timeline includes exact Event/Detection/Candidate/status references, deduplicates sources, orders timestamp ties deterministically, and never strengthens snapshot wording;
- bounded timeline output excludes tokens, arbitrary metadata, raw payloads, and full command lines by default.

### Persistence, concurrency, and failure tests

- SQLAlchemy relationship round-trip through a fresh session for Incident, Candidates, Detections, Events, Device, and status history;
- database checks and uniqueness constraints, including one Incident per Candidate and `incident_key` uniqueness;
- concurrent same-group, same-time-window creation on real PostgreSQL uses advisory locking to produce exactly one Incident and attach both eligible Candidates, or safely fails closed;
- forced Incident failure after Candidate creation leaves Event, Detection, and Candidate rows committed and no partial Incident/association/history rows;
- outer commit failure produces no false `evidence_committed=true` log;
- duplicate retry is a no-op with unchanged Incident key, evidence count, risk, confidence, and timestamps;
- Alembic `upgrade head`, `downgrade 0004_correlation_foundation`, and second upgrade pass on PostgreSQL;
- full API, agent-if-affected, Ruff, strict mypy, and PostgreSQL integration suites pass.

## 14. Assumptions, unresolved decisions, and limitations

### Approved-by-this-spec assumptions

- Incidents are single-device in 6A.
- Only eligible CorrelationCandidates can create or contribute; direct Event/Detection/manual creation is excluded.
- Global promotion floor is score 30 and medium confidence; attachment window default is 3,600 seconds.
- Only `OPEN` and `INVESTIGATING` accept automatic evidence.
- Risk is the capped sum of unique Detection contributions; severity derives from fixed version-1 bands; confidence is maximum eligible Candidate confidence.
- Current `PROCESS_LISTENER_ACTIVITY` is not promotable.

### Decisions intentionally unresolved for later review

- which future production correlation strategies receive promotion policies and their grouping keys/stricter thresholds;
- authenticated operator/user model, role permissions, and public Incident/status API;
- reopen, merge, split, candidate reassignment, cross-device/campaign correlation, and manual Incident creation;
- reconciliation for Candidates left unattached after Incident-processing failure;
- retention, archival, legal hold, and Device/evidence deletion semantics;
- threat taxonomy, malware/actor attribution records, ATT&CK presentation, and analyst annotations;
- notification delivery, response-action approval/execution, UI pagination/redaction policy, and AI analysis schema.

### Known foundation limitations

- With no production promotion policy, initial Milestone 6A creates no automatic Incidents from today's only Candidate strategy. This is deliberate safety, not an unfinished rule.
- The one-hour sliding window can keep a case open indefinitely when eligible evidence continues without a larger gap; there is no maximum Incident duration in 6A.
- Timeline construction is query-time and may need a materialized read model at scale.
- Persisted risk/severity/confidence are deterministic heuristics, not calibrated probabilities.
- No reconciliation worker means an Incident-only failure can leave a valid Candidate unattached until later operational tooling exists.
- No authenticated operator boundary means lifecycle mutation must not be exposed externally in 6A.

## 15. Milestone 6A scope boundary

The later implementation may add only the Incident domain contracts, policy registry/engine foundation, deterministic scoring/grouping, PostgreSQL models/migration, service/savepoint integration, internal timeline/state-machine logic, documentation, and tests defined here.

It must not add Incident UI, public operator workflow without authentication, AI Investigator, notifications, response actions, WebSockets, ransomware/brute-force/port-scan/persistence/DNS/Wi-Fi detection packs, or threat attribution.
