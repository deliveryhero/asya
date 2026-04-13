---
title: "OpenTelemetry tracing: sidecar spans, runtime spans, asya k trace CLI"
status: open
priority: 1
parent: 00001
---

## Problem

The envelope carries trace_id in headers but no spans are emitted.
Debugging message flow requires manually correlating logs across actors.

## Scope

1. **Sidecar (Go)**: emit OTel spans for each envelope hop
   - Span per message: receive → runtime call → publish to next queue
   - Propagate trace context via Pub/Sub message attributes
   - Configure via OTEL_EXPORTER_OTLP_ENDPOINT env var

2. **Runtime (Python)**: emit OTel spans for handler execution
   - Span wrapping the handler call (includes handler name, envelope ID)
   - Auto-instrumented via opentelemetry-api (optional dep)

3. **CLI**: `asya k trace <task-id>` fetches and renders trace
   - Query Jaeger/Tempo/Cloud Trace API
   - ASCII waterfall visualization (like the --trace output)
   - Link to trace UI URL

4. **`asya k send --trace`**: combines send + trace in one command

## Dependencies

- OTEL collector or Cloud Trace configured in the cluster
- `asya patch --all-actors env.OTEL_EXPORTER_OTLP_ENDPOINT=...` for config
