# Detection Engine

Status: planned for Milestones 4-5; no detection or scoring code exists yet.

Rules will be deterministic, explainable, named, versionable, configurable, and independently tested. Detections will reference their source evidence and contribute to a centralized score clamped to 0-100. Correlation will group related signals by device, process identity, executable, relationships, destination, and bounded time windows rather than generating one incident per signal.

Each rule contract will declare an ID, name, description, category, severity, score, required event types, evaluation behavior, generated evidence, and optional verified ATT&CK mapping. Packs will separate process/resource, network, persistence, file activity, authentication, reconnaissance, script execution, DNS, and Wi-Fi behavior rather than accumulating rules in one file.

Every high-value family requires a benign comparison test. High CPU, interpreters, new listeners, new destinations, new APs, and new LAN devices are weak signals by themselves and must not produce malware/tool verdicts without context. Implementation order and telemetry dependencies are tracked in `docs/detection-backlog.md`.
