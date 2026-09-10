# Terminal Operator Console Design

## Goal

Restore the existing terminal-dashboard concept as a supported, tested operator console. `aegisx run` starts PostgreSQL, the API, and the agent, then displays the console in the same terminal. No browser, AI, Decision/Policy, response action, or fabricated security conclusion is included.

## Boundaries

- The console is read-only and uses the accepted Milestone 6A PostgreSQL models.
- The visual shell may be adapted from the rescued Textual prototype, but none of its Gemini, AI, `Incident.decisions`, or fake-demo data is retained.
- Events, Detections, CorrelationCandidates, and Incidents remain visibly separate.
- Empty Incident data is shown truthfully; the console does not create Incidents or add a production promotion policy.
- Query failures produce a bounded operator-facing error without printing credentials or raw telemetry.

## Components

`aegisx_api.console.repository` owns bounded SELECT queries and converts ORM rows into immutable display records while the session is open. It exposes counts and recent Devices, Events, Detections, CorrelationCandidates, and Incidents, then disposes its engine on shutdown.

`aegisx_api.console.app` owns the Textual layout, keyboard bindings, refresh worker, tables, severity/status styling, and lifecycle. `r` refreshes, number keys switch tabs, and `q` exits.

`aegisx_launcher.runtime` continues to own service lifecycle. In normal mode it starts API and agent with their output redirected away from the terminal, starts `aegisx-console` in the foreground, and stops API/agent when the console exits. `--no-ui` preserves the current log-oriented supervision loop.

## Runtime flow

1. Discover the project and environment file.
2. Validate/start PostgreSQL and synchronize API/agent environments.
3. Apply Alembic migrations and wait for `/health/ready`.
4. Start the agent.
5. Start `uv run --project apps/api aegisx-console` in the terminal.
6. When the console exits or the user interrupts, terminate agent and API; stop PostgreSQL only when this launcher instance started it.

Console startup failure is a launcher failure and triggers the same cleanup. Existing single-instance state remains authoritative.

## Display contract

The top row shows active Devices, total Events, total Detections, total Candidates, and open Incidents. Tabs show bounded recent rows for each object type. Values are truncated for terminal safety; no bearer tokens, token digests, environment secrets, full raw payloads, or exception messages are displayed.

## Verification

- Repository tests use an isolated async SQLite database and accepted ORM models.
- Textual pilot tests verify mount, table population, refresh, empty state, and safe error display.
- Launcher tests verify normal TUI command order, `--no-ui`, console exit propagation, and cleanup.
- Full API, agent, launcher, PostgreSQL migration, Ruff, mypy, Compose, and real terminal smoke checks run before completion.

## Distribution boundary

This milestone makes the checkout runnable through `aegisx run`; it is not yet the cross-machine release artifact. Portable installation, signed/checksummed releases, and host-agent deployment are a subsequent packaging step after the console workflow is verified.
