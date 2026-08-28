# AegisX API

The API will own device registration, validated telemetry ingestion, persistence, deterministic detection, incident correlation, realtime updates, and read-only AI investigation.

It does not collect host telemetry or render the user interface. Milestone 1 currently implements liveness/readiness and Linux device registration. Run it with `~/.local/bin/uv run uvicorn aegisx_api.main:app --reload` after applying Alembic migrations.
