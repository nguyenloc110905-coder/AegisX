# API

Status: Milestones 1 and 3 complete; alignment patch applied before Milestone 4.

Implemented endpoints:

- `GET /health/live` checks the API process without requiring PostgreSQL.
- `GET /health/ready` executes `SELECT 1` and returns 503 when PostgreSQL is unavailable.
- `POST /api/v1/devices/register` accepts a bounded Linux device profile and returns the device plus a one-time opaque token. Only the SHA-256 token digest is stored. Reusing an external device ID returns 409.
- `POST /api/v1/telemetry/events` requires the device bearer token, accepts a non-empty typed batch up to the configured `telemetry_batch_limit`, and returns accepted and duplicate counts with HTTP 202. Oversized batches return a stable 422 error containing the active limit.

Supported event types are `process.started`, `process.resource_usage`, `system.status`, `network.listener_observed`, and `network.connection_observed`, all at schema version 1. Event UUIDs are globally unique and make retries idempotent. Network address, port, protocol, state, and process association are promoted for indexed queries. The FastAPI lifespan disposes the async database engine on shutdown. Incident queries, AI analysis, and WebSocket updates remain planned. PostgreSQL access uses SQLAlchemy async and explicit Alembic migrations.
