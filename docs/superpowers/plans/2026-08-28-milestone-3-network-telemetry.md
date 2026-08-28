# AegisX Milestone 3 Network Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect active IP connections and listening sockets on Linux, associate processes where available, ingest typed events, and demonstrate observation of a local HTTP listener.

**Architecture:** Add a psutil-backed NetworkCollector behind the existing collector boundary. Normalize listeners and connections as distinct schema-version-1 event types, promote searchable network fields into Event columns through a migration, and keep permission failures non-fatal.

**Tech Stack:** Python 3.12, psutil, FastAPI/Pydantic, SQLAlchemy/Alembic, PostgreSQL, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-aegisx-platform-design.md`

## Tasks

1. Write failing agent tests for TCP listeners, connected TCP/UDP sockets, missing PID, bounding, and access denial.
2. Implement NetworkCollector and include it in one-shot collection without exceeding API batch bounds.
3. Write failing API tests for typed `network.listener` and `network.connection` payloads.
4. Add schema models, promoted local/remote address/port/protocol/state fields, and Alembic migration.
5. Start a local Python HTTP server, run the agent, verify the listener event and PID/port in PostgreSQL, run all quality gates, update docs, and push.
