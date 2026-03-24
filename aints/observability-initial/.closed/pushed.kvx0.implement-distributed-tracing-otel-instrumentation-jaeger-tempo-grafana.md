---
title: "Implement distributed tracing: OTEL instrumentation + Jaeger/Tempo in Grafana"
priority: 1 # high
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/observability-initial/kvx0.implement-distributed-tracing-otel-instrumentation-jaeger-tempo-grafana
  - branch:observability-initial/kvx0.implement-distributed-tracing-otel-instrumentation-jaeger-tempo-grafana
---



## Goal

Add end-to-end distributed tracing to Asya so that a user can trace a single message
through the actor mesh — from gateway ingress through each sidecar/runtime hop to x-sink.

## Requirements

### 1. Trace Context Propagation
- Gateway: generate `traceparent` (W3C Trace Context) on task creation, inject into envelope `headers.traceparent`
- Sidecar: extract `traceparent` from envelope headers, create child span for each processing cycle, inject updated `traceparent` into outgoing envelope
- Span attributes: `asya.actor`, `asya.flow`, `asya.envelope_id`, `asya.queue`

### 2. OTEL Exporter Configuration
- Sidecar: add OTEL trace exporter (OTLP/gRPC to collector)
- Gateway: add OTEL trace exporter
- Env vars: `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME` (auto-set to actor name)

### 3. Trace Backend
- Deploy Jaeger or Grafana Tempo in the playground chart (`sampleMonitoring` section)
- Configure Grafana data source for traces (Jaeger or Tempo)
- Enable trace-to-logs correlation in Grafana (link from trace span to pod logs)

### 4. Grafana Integration
- Add trace exploration panel or link in the existing "Asya - Actors Overview" dashboard
- Or: rely on Grafana Explore for ad-hoc trace queries

### 5. Helm Chart Changes
- asya-crossplane: inject OTEL env vars into sidecar container spec
- asya-playground: add Jaeger/Tempo deployment, OTEL collector (optional)
- asya-gateway: add OTEL middleware for HTTP handlers

## Non-Goals (for now)
- Runtime (Python) tracing — runtime is dependency-free by design
- User handler custom spans — covered by aint 1f4g
- Cloud-native backends (Cloud Trace, Datadog) — start with open-source stack

## References
- Envelope spec: `docs/reference/specs/envelope.md`
- Existing aints: `1f4g` (OTEL env vars for user metrics), `1fbs` (retry tracing)
- Sidecar metrics already exported at `:8080/metrics` (Prometheus)
- Go OTEL SDK: `go.opentelemetry.io/otel`
