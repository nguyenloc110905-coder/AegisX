# AegisX Agent

The agent will identify a Linux device, collect host telemetry through isolated collectors, normalize events, buffer them locally, and deliver them to the API.

It does not detect with AI, remediate the host, or run arbitrary commands. Milestone 2 currently implements stable private identity/credentials, real Linux system and process collectors, API registration, typed normalization, batching, and one-shot delivery.

With the API and PostgreSQL running:

```bash
make agent-sync
make agent-once
```

Override `AEGISX_API_URL` and `AEGISX_AGENT_STATE_DIR` when needed. Default state is under `~/.local/state/aegisx`. Identity, credentials, and the SQLite outbox use mode `0600`.

When the API is offline, `collect-once` exits successfully with `delivery_status=deferred` and a non-zero `queued` count. Run it again after the API recovers; queued events are delivered before the outbox is cleared. The queue defaults to 10,000 events and evicts the oldest entries rather than growing without bound.

Periodic retry/backoff, permanent-error quarantine, and background service lifecycle are not implemented yet.
