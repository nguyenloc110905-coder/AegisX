# Threat Model

Status: initial assumptions; this document will be expanded with implemented data flows.

## Protected assets

- Device identity and ingestion credentials
- Endpoint telemetry and potentially sensitive process command lines
- Detection evidence and Incident history
- Backend and database availability and integrity

## Trust boundaries

The endpoint, transport, API, database, browser, and local validation environment are separate trust boundaries. Primary threats include forged or replayed telemetry, malformed or oversized payloads, secret leakage, log injection, excessive collection privileges, denial of service, and unsafe validation scripts.

## Required controls

Use least privilege, authenticated devices, bounded and typed input, idempotency, secret redaction, migration-controlled schemas, and lab-only reversible simulations. Local development credentials and HTTP transport are not production security controls.

Polling telemetry is incomplete by construction: short-lived activity can occur between snapshots,
and permission or race failures deliberately defer transition claims. The terminal console therefore
shows telemetry recency separately from enrollment and permanently states that AegisX does not
prevent attacks. A recent timestamp is evidence of successful authenticated ingestion, not proof of
host safety.

Development database cleanup is destructive. It is exposed only as the explicit
`aegisx dev-reset --yes` command, is refused outside the `development` environment, and shares the
launcher's single-instance lock. Normal stop/shutdown preserves PostgreSQL volumes. The reset does
not delete the host agent's private identity, credentials, outbox, or quarantine.
