# Architecture

Status: foundation implemented; application components are planned.

AegisX is a monorepo with three deployable applications: a Linux endpoint agent, one modular FastAPI backend, and a small Next.js web UI. PostgreSQL is authoritative storage. Redis, Kafka, Elasticsearch, Kubernetes, and microservice decomposition are excluded until a measured requirement proves otherwise.

The intended data flow is collector observation, normalized event, authenticated batch ingestion, deterministic detection, correlation, and Incident update. Decision and response remain future independent layers. Module boundaries and security constraints are defined in the approved designs under `docs/superpowers/specs/`.

Detection architecture follows `attack technique -> observable behavior -> telemetry -> rule -> correlation -> Incident`. Rules remain modular detection packs behind one registry, scoring policy, and evidence contract. ATT&CK IDs are optional metadata and never a prerequisite for correct behavioral detection.
