# Endpoint Agent

Status: Milestone 2 in progress; one-shot Linux collection and delivery are implemented.

The Linux agent runs independently of the UI. It currently owns stable UUID identity, private token persistence, configurable one-shot collection, normalization, batching, and API delivery. `SystemCollector` reports host/kernel/uptime/CPU/RAM. `ProcessCollector` emits bounded lifecycle and resource observations while skipping process disappearance and permission races.

OS access is isolated behind collector interfaces and normal tests do not require root. Durable outbox/retry, periodic scheduling, operational logging, and systemd lifecycle remain active Milestone 2 work.
