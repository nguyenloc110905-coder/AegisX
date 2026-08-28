# Threat Model

Status: initial assumptions; this document will be expanded with implemented data flows.

## Protected assets

- Device identity and ingestion credentials
- Endpoint telemetry and potentially sensitive process command lines
- Detection evidence, incident history, and AI analyses
- Backend and database availability and integrity

## Trust boundaries

The endpoint, transport, API, database, browser, AI provider, and local validation environment are separate trust boundaries. Primary threats include forged or replayed telemetry, malformed or oversized payloads, secret leakage, log injection, excessive collection privileges, prompt injection through telemetry, denial of service, and unsafe validation scripts.

## Required controls

Use least privilege, authenticated devices, bounded and typed input, idempotency, secret redaction, migration-controlled schemas, curated AI evidence, no AI tool execution, and lab-only reversible simulations. Local development credentials and HTTP transport are not production security controls.
