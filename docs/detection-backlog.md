# Detection Backlog

Status: requirements accepted; implementation intentionally deferred until Milestones 4-5 and required collectors exist.

## Design rules

- Detect reusable behavior, not malware families or guessed tools.
- Correlate weak signals before escalating severity.
- Preserve evidence IDs, facts, hypotheses, uncertainty, and conclusions separately.
- Keep rules modular by category with centralized registry and scoring.
- Add one malicious-like safe scenario and at least one benign comparison per high-value family.
- Use ATT&CK mappings only when technically justified.

## Ordered families and dependencies

| Order | Family | Required telemetry | Example hypothesis | Benign comparison |
|---:|---|---|---|---|
| 1 | Resource abuse | process lifecycle/resource, executable baseline, later network/persistence | Possible resource abuse or miner-like activity | compilation or video encoding |
| 2 | Listener/network | sockets, process association, destinations, inbound activity | New listening service or unusual connection | local development server/browser |
| 3 | Persistence | systemd, user services, autostart, cron, shell startup files | New or modified persistence mechanism | labeled reversible lab unit |
| 4 | File activity | create/modify/rename/delete rates and responsible process | Possible mass file modification | generated temporary-file workload |
| 5 | Authentication | failed/success events, source, user, service, time window | Possible brute-force attempt | synthetic normal login failures |
| 6 | Reconnaissance | source/destination ports and short-lived attempts | Possible port scanning or service discovery | normal client connection pattern |
| 7 | Script execution | process tree, script file, path, network and privilege context | Suspicious script/interpreter execution | ordinary Python/Bash development |
| 8 | DNS | query rate, domains, failures and process association when available | Suspicious DNS activity | browser-driven DNS burst |
| 9 | Wi-Fi | SSID/BSSID/security/channel/signal history | Possible rogue or Evil Twin AP | legitimate mesh/multi-AP network |
| 10 | Local LAN | observed MAC/IP history, inbound activity, services | New LAN device observed | ordinary newly joined owned device |

## Correlation keys

Initial deterministic correlation uses device ID, PID/PPID, executable and file paths, username, source/destination, timestamps, and process-tree relationships. Example compound incidents include executable + sustained CPU + recurring outbound + persistence; listener + new LAN host + inbound connection; and new script + interpreter + outbound + privilege change.

## MVP target

Aim for 8-10 demonstrable scenarios only when their telemetry is reliable. Depth wins: five evidence-rich detections with correlation, safe validation, and false-positive resistance are better than fifty shallow rules.
