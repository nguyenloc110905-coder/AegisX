# API

Status: Milestone 1 in progress.

Implemented endpoints:

- `GET /health/live` checks the API process without requiring PostgreSQL.
- `GET /health/ready` executes `SELECT 1` and returns 503 when PostgreSQL is unavailable.
- `POST /api/v1/devices/register` accepts a bounded Linux device profile and returns the device plus a one-time opaque token. Only the SHA-256 token digest is stored. Reusing an external device ID returns 409.

Authenticated telemetry ingestion, incident queries, AI analysis, and WebSocket updates remain planned. PostgreSQL access uses SQLAlchemy async and explicit Alembic migrations.
