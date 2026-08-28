# Event Model

Status: schema version 1 implemented for process, system, and network telemetry.

Every normalized request event contains `id`, `schema_version`, `timestamp`, `event_type`, `source`, `severity_hint`, typed `data`, and bounded `metadata`; the authenticated device supplies `device_id`. Pydantic discriminates payloads by explicit event type. The database promotes PID, PPID, executable, device, type, and timestamp for correlation and stores the remaining validated payload as JSON.

Implemented version 1 payloads:

- `process.started`: emitted only when a `(PID, create_time)` identity is absent from the previous persisted process baseline. The first collection creates the baseline and does not claim that already-running processes just started.
- `process.resource_usage`: PID, non-negative CPU percentage, and non-negative memory bytes.
- `system.status`: hostname, OS, kernel, uptime, CPU count, and total memory.
- `network.listener_observed`: snapshot evidence that a listener exists at collection time; it does not claim the listener was newly opened.
- `network.connection_observed`: snapshot evidence that a connection exists at collection time; it does not claim an opened/closed transition.

No network opened/closed event exists yet because the collector does not persist and compare socket state across cycles.
