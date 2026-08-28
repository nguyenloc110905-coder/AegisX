# API

Status: Milestone 1 in progress.

Implemented endpoints:

- `GET /health/live` checks the API process without requiring PostgreSQL.
- `GET /health/ready` executes `SELECT 1` and returns 503 when PostgreSQL is unavailable.
- `POST /api/v1/devices/register` accepts a bounded Linux device profile and returns the device plus a one-time opaque token. Only the SHA-256 token digest is stored. Reusing an external device ID returns 409.
- `POST /api/v1/telemetry/events` requires the device bearer token, accepts 1-100 typed events, and returns accepted and duplicate counts with HTTP 202.

Supported event types are `process.started`, `process.resource_usage`, and `system.status`, all at schema version 1. Event UUIDs are globally unique and make retries idempotent. Incident queries, AI analysis, and WebSocket updates remain planned. PostgreSQL access uses SQLAlchemy async and explicit Alembic migrations.
