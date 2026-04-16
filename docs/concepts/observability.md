---
description: "Observability: OpenTelemetry tracing, Prometheus metrics, structured logging, Grafana dashboards"
---

# Built-in Observability

In a distributed actor mesh, understanding what happened and where requires
first-class observability. Asya integrates with the standard Kubernetes
observability stack: OpenTelemetry, Prometheus, and structured logging.

## Distributed tracing

Every envelope carries W3C Trace Context headers (`traceparent`, `tracestate`).
The gateway generates the root trace when a task is created. Each sidecar
extracts the trace context, creates spans for envelope processing, and injects
updated context into outgoing envelopes.

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to enable tracing. Traces appear in any
OTLP-compatible backend: Tempo, Jaeger, Cloud Trace, Datadog, or Honeycomb.

Span structure per actor hop:
- `actor.process` — full envelope processing (SpanKindConsumer)
- `actor.runtime.call` — handler execution via Unix socket
- `actor.resiliency.policy` — retry/exhausted decisions
- `actor.queue.send` — outbound dispatch (SpanKindProducer)

## Prometheus metrics

Every sidecar exposes Prometheus metrics:

| Metric | What it measures |
|--------|-----------------|
| Queue depth | Messages waiting to be processed |
| Processing time | Handler execution duration (histogram) |
| Error rate | Failed handler invocations |
| Retry count | Number of retries per message |

These metrics feed into KEDA for autoscaling and into Grafana dashboards for
operational visibility.

## Structured logging

All components emit structured JSON logs with consistent fields:

- `trace_id` — correlates logs across actors in the same pipeline
- `envelope_id` — identifies the specific message
- `actor` — which actor produced the log
- `level` — standard severity levels

This makes it possible to filter logs for a single pipeline execution across all
actors, even when hundreds of messages are in flight.

## Grafana dashboards

Pre-built Grafana dashboards provide visibility into:

- Per-actor throughput and latency
- Queue depth trends and scaling events
- Error rates and retry patterns
- End-to-end pipeline latency

## Further reading

- [Observability operations guide](../setup/ops-observability.md) —
  configuration, dashboard setup, alerting
