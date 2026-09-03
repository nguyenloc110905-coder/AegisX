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

Process lifecycle comparison is skipped and the prior baseline is retained when enumeration fails, any process record becomes inaccessible or disappears during lookup, or `create_time` is unavailable. One failed lookup therefore cannot manufacture an exit. The collector scans every returned process identity even when detailed resource output reaches `max_processes`, so the output bound cannot create false absence. PID reuse is two transitions: the old `(PID, create_time)` exits and the new incarnation starts. Baseline version 2 is written with mode `0600` through `fsync` plus atomic replacement and can read the prior version-1 key format.

No network opened/closed event exists yet because the collector does not persist and compare socket state across cycles.

## Detection evidence

Validated new Events are evaluated before the ingestion transaction commits. `PROCESS_STARTED` uses `process.started`; `LISTENER_OBSERVED` uses the snapshot-safe `network.listener_observed`. Every persisted Detection has a foreign key to its source Event and records its evidence Event UUIDs. Duplicate Event UUIDs are not evaluated again.
