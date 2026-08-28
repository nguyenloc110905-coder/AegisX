# AegisX Milestone 2 Linux Agent Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a lightweight Linux agent that identifies its device, collects real process/system telemetry, normalizes typed events, registers with the API, and reliably delivers bounded batches.

**Architecture:** Use a separate Python 3.12 package with OS access behind collector protocols, pure normalization functions, an HTTP client isolated from collection, and a SQLite-backed bounded outbox for transient failures. The CLI supports a one-shot mode first so collection and delivery are easy to verify before systemd lifecycle work.

**Tech Stack:** Python 3.12, uv, psutil, HTTPX, Pydantic Settings, structlog, SQLite standard library, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-08-28-aegisx-platform-design.md`

## Global Constraints

- Fedora/Linux is the primary target and normal operation does not require root.
- Collectors return typed observations and handle per-process permission/disappearance races.
- Stable device identity is persisted with restrictive file permissions; tokens never enter logs.
- Collection and transmission intervals are configurable and bounded.
- The outbox has bounded rows/bytes and never grows indefinitely.
- Unit tests mock OS and transport boundaries; final verification uses real local telemetry and PostgreSQL.

---

### Task 1: Agent Project, Identity, and System Telemetry

Create `apps/agent/pyproject.toml` and `src/aegisx_agent` modules for settings, identity, event models, collector protocol, system collector, logging, and CLI. Tests first prove stable identity persistence, UUID/timestamp normalization, real basic system fields, and non-root behavior.

### Task 2: Process Collector

Add a psutil adapter and ProcessCollector that emits bounded `process.started` snapshots with PID, PPID, name, executable, user, command line, CPU, memory, and create time where available. Tests first cover access denied, vanished processes, command truncation, and fixture normalization without privileged access.

### Task 3: API Client and Durable Outbox

Add device registration, token persistence, authenticated batch delivery, transient/permanent error classification, exponential retry policy, and a bounded SQLite outbox. Tests first verify token redaction, successful delivery, retry retention, invalid-event quarantine, duplicate-safe resend, and queue eviction policy.

### Task 4: One-shot Orchestration and Runtime Verification

Add `aegisx-agent collect-once`, root Make targets, configuration docs, and operational logging. Run the real agent against the local API/PostgreSQL, verify system/process events and device last-seen state, measure one-shot duration/resource use, run all agent/API/foundation gates, and update `docs/progress.md` before pushing.
