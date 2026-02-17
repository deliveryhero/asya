---
title: "Observability: error retry metrics and tracing for debuggability by message ID + actor name"
status: open
priority: 2 # medium
type: task
---

Investigate and implement observability for the error retry flow. Each retry attempt by the error-handler crew actor must emit structured metrics/logs/traces that enable: (1) querying retry history by message ID (how many retries, what errors, what delays), (2) querying retry patterns by actor name (which actors fail most, error type distribution), (3) end-to-end latency analysis including retry delays across the full pipeline. Explore: OpenTelemetry integration, structured logging format, Grafana dashboard templates, and whether the sidecar progress reporter should emit retry events to the gateway. The retry data must exist in the observability stack even though it is NOT accumulated in the message itself (message carries only current retry state).


---
_Migrated from beads `asya-si1r`_
