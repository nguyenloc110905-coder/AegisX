# Endpoint Agent

Status: Milestone 5B complete and cross-project verification passed.

The Linux agent runs independently of the terminal console. It currently owns stable UUID identity, private token persistence, configurable one-shot collection, normalization, batching, and API delivery. `SystemCollector` reports host/kernel/uptime/CPU/RAM. `ProcessCollector` persists a private `(PID, create_time)` baseline, emits `process.started` for a new incarnation and `process.exited` only when that incarnation is absent from the next complete snapshot. Per-process resource observations are high volume and disabled by default; `AEGISX_EMIT_PROCESS_RESOURCE_USAGE=true` opts in without changing lifecycle comparison. PID reuse produces an exit for the old incarnation and a start for the new one. If enumeration or even one process lookup is incomplete, lifecycle comparison and baseline replacement are skipped; a failed lookup is never treated as exit evidence. The output cap does not cap the identity scan, but separately caps exit events; excess exits are omitted rather than replayed with stale timing. The baseline is atomically replaced after file and directory synchronization and remains private mode `0600`.

`NetworkCollector` compares complete consecutive snapshots for endpoint-presence `opened`/`closed` transitions. Listener identity is protocol plus canonical local endpoint; connection identity adds the canonical remote endpoint. PID and state are attributes, not identity. The first snapshot is baseline-only, a repeated snapshot cannot reopen a socket, and failed/malformed snapshots retain the last trustworthy baseline. High-volume `network.listener_observed` and `network.connection_observed` output is disabled by default and can be enabled with `AEGISX_EMIT_NETWORK_SNAPSHOT_OBSERVATIONS=true`; the private full baseline and transition behavior are unchanged. Duplicate endpoint identities may be observed when opted in but do not receive an arbitrary opened attribution. The baseline uses the same private, synchronized atomic-write discipline as process state. Collector permission/race failures do not crash the agent.

Default collection is therefore transition-oriented, not realtime prevention. Polling can miss activity
that begins and ends between snapshots. A quiet cycle means no proved transition under current
visibility; it does not prove that the host was attack-free.

OS access is isolated behind collector interfaces and normal tests do not require root. Collection
writes normalized Events to a private SQLite local journal before any network operation. Schema v2
keeps a global sequence, canonical payload, SHA-256 checksum, evidence priority, and delivery state.
Acknowledgement changes `PENDING` to `ACKED` without deleting the Event; permanent 400/422 isolation
changes it to `QUARANTINED`. Transport and 429/5xx failures leave it `PENDING`. UUID uniqueness and
oldest-first delivery preserve idempotent retry.

`AsyncLocalTelemetryStore` offloads SQLite work from the event loop and serializes its one connection;
cancellation waits for an in-flight worker before releasing the lock. Storage pressure prunes only
expired `ACKED` rows allowed by versioned local retention. It never evicts `PENDING`, `QUARANTINED`,
unknown, or not-yet-expired security evidence to accept a new batch. A rejected batch produces
`coverage_status=degraded` and a bounded coverage gap; a private atomic sidecar is the fallback when
SQLite itself cannot record that gap. On a failed legacy schema migration, the agent delivers existing
v0 rows only and stops collecting new telemetry until migration can succeed.

`aegisx local-data-status`, `local-verify`, and local prune operate directly on endpoint state without
Compose or PostgreSQL. The checksum detects accidental corruption but is unsigned and not tamper-proof.
Selective sync, realtime kernel collection, local Detection, systemd packaging, and Response remain
future work.
