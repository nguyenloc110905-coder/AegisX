# API

Status: planned from Milestone 1; no HTTP endpoint exists yet.

The FastAPI application will expose health/readiness, authenticated device management, validated batched telemetry ingestion, incident queries, AI analysis operations, and WebSocket updates. PostgreSQL access will use SQLAlchemy async and Alembic migrations. Stable validation errors must not expose secrets or stack traces.
