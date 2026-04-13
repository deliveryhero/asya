---
title: Configure OTEL env vars for user metrics in runtime container
status: open
priority: 2
---

## Summary
Document and configure OpenTelemetry environment variables for the runtime container so users can use the Python OTEL SDK out of the box.

## Goal
Users should be able to:
```python
from opentelemetry import metrics
meter = metrics.get_meter("my-handler")
counter = meter.create_counter("tokens_processed")
counter.add(150, {"model": "gpt-4"})
```
And have metrics automatically exported to the sidecar's Prometheus endpoint.

## Env vars to configure
Set these in the runtime container (via operator):
- `OTEL_SERVICE_NAME` - actor name from CRD
- `OTEL_EXPORTER_OTLP_ENDPOINT` - point to sidecar OTLP receiver
- `OTEL_EXPORTER_OTLP_PROTOCOL` - grpc or http/protobuf
- `OTEL_METRICS_EXPORTER` - otlp
- `OTEL_TRACES_EXPORTER` - none (or otlp if we want traces later)
- `OTEL_LOGS_EXPORTER` - none

## Sidecar changes
- Add OTLP receiver endpoint (e.g., localhost:4317)
- Bridge received OTEL metrics to Prometheus registry
- Consider using opentelemetry-collector-contrib or lightweight bridge

## Documentation
- Document in `src/asya-runtime/README.md` how to use OTEL in handlers
- Add example handler with OTEL metrics
- List all env vars and their values

## Files to modify
- `src/asya-operator/internal/controller/` - inject OTEL env vars
- `src/asya-sidecar/` - add OTLP receiver
- `src/asya-runtime/README.md` - document usage
- `examples/` - add OTEL metrics example


---
_Migrated from beads `asya-8mi`_
