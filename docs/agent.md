# Endpoint Agent

Status: planned from Milestone 2; no agent executable exists yet.

The Linux agent will run independently of the UI and own stable device identity, configurable collection, normalization, bounded durable delivery, retry, and safe operational logging. OS access will be isolated behind collector interfaces. Permission failures must degrade gracefully, and normal unit tests must not require root access.
