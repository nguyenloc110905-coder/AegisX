# AegisX API

The package also provides the read-only `aegisx-console` Textual operator interface used by `aegisx run`.

The API owns device registration, validated telemetry ingestion, persistence, deterministic detection, correlation, and Incident foundation services. It has no AI integration or response-execution authority.

It does not collect host telemetry or render the user interface. Milestone 1 currently implements liveness/readiness and Linux device registration. Run it with `~/.local/bin/uv run uvicorn aegisx_api.main:app --reload` after applying Alembic migrations.
