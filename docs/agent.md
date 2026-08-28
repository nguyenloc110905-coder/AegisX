# Endpoint Agent

Status: Milestone 2 in progress; one-shot Linux collection and delivery are implemented.

The Linux agent runs independently of the UI. It currently owns stable UUID identity, private token persistence, configurable one-shot collection, normalization, batching, and API delivery. `SystemCollector` reports host/kernel/uptime/CPU/RAM. `ProcessCollector` emits bounded lifecycle and resource observations while skipping process disappearance and permission races.

OS access is isolated behind collector interfaces and normal tests do not require root. Collection writes normalized events to a private bounded SQLite outbox before any network operation. Transport and 429/5xx failures leave events queued and trigger bounded exponential backoff. The next successful cycle flushes oldest-first and resets the interval. Invalid 400/422 batches are divided to isolate individual bad events in bounded quarantine; 401/403 never delete queued evidence. Continuous mode emits structured JSON cycle logs without credentials. A packaged systemd unit remains later hardening work.
