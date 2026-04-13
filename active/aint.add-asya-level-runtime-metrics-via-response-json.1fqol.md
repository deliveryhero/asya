---
title: Add Asya-level runtime metrics via response JSON
status: open
priority: 2
tags:
  - type:feature
---

## Summary
Embed standard Asya runtime metrics in the envelope response JSON so the sidecar can aggregate and expose them via Prometheus.

## Metrics to capture in runtime
- `payload_deserialization_duration_seconds` - time to parse incoming JSON payload
- `payload_serialization_duration_seconds` - time to serialize response JSON
- `handler_execution_duration_seconds` - time spent in user handler function
- `handler_error_class` - Python exception class name (if error occurred)
- `handler_error_message` - Python exception message (if error occurred)

## Response format change
Add optional `_metrics` field to runtime response:
```json
[
  {
    "payload": {...},
    "route": {...},
    "_metrics": {
      "deser_ms": 1.2,
      "ser_ms": 0.8,
      "handler_ms": 45.3,
      "error_class": null
    }
  }
]
```

## Sidecar changes
- Parse `_metrics` from runtime response
- Record to existing Prometheus metrics (new histograms/counters)
- Remove `_metrics` before forwarding envelope

## Files to modify
- `src/asya-runtime/asya_runtime.py` - add timing instrumentation
- `src/asya-sidecar/internal/runtime/client.go` - parse _metrics field
- `src/asya-sidecar/internal/metrics/metrics.go` - add new metric types
- `src/asya-sidecar/METRICS.md` - document new metrics


---
_Migrated from beads `asya-nj9`_
