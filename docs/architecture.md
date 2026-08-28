# Architecture

Status: foundation implemented; application components are planned.

AegisX is a monorepo with three deployable applications: a Linux endpoint agent, one modular FastAPI backend, and a small Next.js web UI. PostgreSQL is authoritative storage. Redis, Kafka, Elasticsearch, Kubernetes, and microservice decomposition are excluded until a measured requirement proves otherwise.

The intended data flow is collector observation, normalized event, authenticated batch ingestion, deterministic detection, centralized risk scoring, correlation, incident update, optional notification, and optional read-only AI analysis. Module boundaries and security constraints are defined in the approved design under `docs/superpowers/specs/`.
