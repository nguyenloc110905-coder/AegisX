# Event Model

Status: schema version 1 implemented for initial process and system telemetry.

Every normalized request event contains `id`, `schema_version`, `timestamp`, `event_type`, `source`, `severity_hint`, typed `data`, and bounded `metadata`; the authenticated device supplies `device_id`. Pydantic discriminates payloads by explicit event type. The database promotes PID, PPID, executable, device, type, and timestamp for correlation and stores the remaining validated payload as JSON.

Implemented version 1 payloads:

- `process.started`: PID, PPID, name, optional executable/user/start time, and bounded command-line arguments.
- `process.resource_usage`: PID, non-negative CPU percentage, and non-negative memory bytes.
- `system.status`: hostname, OS, kernel, uptime, CPU count, and total memory.
