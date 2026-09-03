# Event Model

Status: schema version 1 implemented for process, system, and network telemetry.

Every normalized request event contains `id`, `schema_version`, `timestamp`, `event_type`, `source`, `severity_hint`, typed `data`, and bounded `metadata`; the authenticated device supplies `device_id`. Pydantic discriminates payloads by explicit event type. The database promotes PID, PPID, executable, device, type, and timestamp for correlation and stores the remaining validated payload as JSON.

Implemented version 1 payloads:

- `process.started`: emitted only when a `(PID, create_time)` identity is absent from the previous persisted process baseline. The first collection creates the baseline and does not claim that already-running processes just started.
- `process.exited`: emitted only when a prior `(PID, create_time)` identity is absent from the next complete process snapshot. Its `started_at` identifies the exited incarnation; the Event envelope timestamp is when absence was observed, not a claimed kernel exit time.
- `process.resource_usage`: PID, non-negative CPU percentage, and non-negative memory bytes.
- `system.status`: hostname, OS, kernel, uptime, CPU count, and total memory.
- `network.listener_observed`: snapshot evidence that a listener exists at collection time; it does not claim the listener was newly opened.
- `network.connection_observed`: snapshot evidence that a connection exists at collection time; it does not claim an opened/closed transition.
- `network.listener_opened` / `network.listener_closed`: a canonical listener endpoint changed from absent to present or present to absent across two complete consecutive snapshots.
- `network.connection_opened` / `network.connection_closed`: a canonical local/remote endpoint tuple changed from absent to present or present to absent across two complete consecutive snapshots.

Process lifecycle comparison is skipped and the prior baseline is retained when enumeration fails, any process record becomes inaccessible or disappears during lookup, or `create_time` is unavailable. One failed lookup therefore cannot manufacture an exit. The collector scans every returned process identity even when detailed resource output reaches `max_processes`, so the output bound cannot create false absence. PID reuse is two transitions: the old `(PID, create_time)` exits and the new incarnation starts. Baseline version 2 is written with mode `0600` through `fsync` plus atomic replacement and can read the prior version-1 key format.

Listener identity is `(protocol, canonical local IP, local port)`. Connection identity adds canonical remote IP and remote port. PID and socket state are evidence attributes, not identity, because OS visibility can change between snapshots. The first snapshot establishes an atomic private baseline and emits observations only; repeated snapshots remain observation-only. A collection failure or malformed address suppresses all transitions and baseline replacement. Duplicate canonical identities remain observed but do not produce an opened transition with an arbitrary process association; their baseline PID is recorded as unavailable. The collector never claims kernel open/close timestamps or a TCP handshake—only endpoint presence transitions between its snapshots. Observations and transitions are separately bounded by `max_network_connections`, so excess truthful transitions may be omitted rather than emitted later from stale state.

## Detection evidence

Validated new Events are evaluated before the ingestion transaction commits. `PROCESS_STARTED` uses `process.started`; `LISTENER_OBSERVED` uses the snapshot-safe `network.listener_observed`. Every persisted Detection has a foreign key to its source Event and records its evidence Event UUIDs. Duplicate Event UUIDs are not evaluated again.
