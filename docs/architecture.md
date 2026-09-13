# Architecture

Status: foundation implemented; application components are planned.

AegisX is a monorepo with a Linux endpoint agent, one modular FastAPI backend, and a reserved web
directory with no implemented web UI. PostgreSQL is authoritative central storage for Detection,
CorrelationCandidate, and Incident records. The agent additionally keeps its generated Events in a
private endpoint journal before delivery; this is not a second Detection or Incident database. Redis,
Kafka, Elasticsearch, Kubernetes, and microservice decomposition are excluded until a measured
requirement proves otherwise.

The implemented evidence path is:

```text
collector -> normalized Event -> local journal PENDING -> authenticated ingestion
          -> local ACKED/QUARANTINED          -> Detection -> CorrelationCandidate -> Incident
```

Local append must commit before network delivery. A local write failure prevents send and marks the
collection cycle degraded. Selective synchronization is not implemented, so every successfully
journaled Event remains eligible for the existing server delivery path. Decision and Response remain
future independent layers; a Detection cannot directly execute an action. Module boundaries and
security constraints are defined in the approved designs under `docs/superpowers/specs/`.

Detection architecture follows `attack technique -> observable behavior -> telemetry -> rule -> correlation -> Incident`. Rules remain modular detection packs behind one registry, scoring policy, and evidence contract. ATT&CK IDs are optional metadata and never a prerequisite for correct behavioral detection.
