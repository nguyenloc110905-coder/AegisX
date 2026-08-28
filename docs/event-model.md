# Event Model

Status: planned for Milestones 1-3; no event schema is executable yet.

Every normalized event will contain `id`, `schema_version`, `device_id`, `timestamp`, `event_type`, `source`, `severity_hint`, typed `data`, and bounded `metadata`. Explicit event types and Pydantic payload models will prevent the database from becoming an arbitrary JSON dump. Searchable correlation keys will be promoted to indexed relational columns when their use is implemented.
