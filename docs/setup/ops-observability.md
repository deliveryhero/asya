---
description: "Observability ops: Prometheus metrics, Grafana dashboards, alerting rules, OpenTelemetry setup"
---

# Observability

This guide shows how to set up monitoring for Asya deployments using Prometheus and Grafana.

## Overview

Asya components expose Prometheus metrics. Only the **sidecar** exposes metrics - runtime uses different observability approaches.

All sidecar metrics use namespace `asya_actor` (configurable via `ASYA_METRICS_NAMESPACE`).

## Metrics Reference

### Message Counters

- `asya_actor_messages_received_total{queue, transport}` - Messages received from queue
- `asya_actor_messages_processed_total{queue, status}` - Successfully processed (status: success, empty_response, end_consumed)
- `asya_actor_messages_sent_total{destination_queue, message_type}` - Messages sent to queues (message_type: routing, sink, sump)
- `asya_actor_messages_failed_total{queue, reason}` - Failed messages by reason
  - Reasons: `parse_error`, `runtime_error`, `transport_error`, `validation_error`, `route_mismatch`, `error_queue_send_failed`

### Duration Histograms

- `asya_actor_processing_duration_seconds{queue}` - Total processing time (queue receive → queue send)
- `asya_actor_runtime_execution_duration_seconds{queue}` - Runtime execution time only
- `asya_actor_queue_receive_duration_seconds{queue, transport}` - Time to receive from queue
- `asya_actor_queue_send_duration_seconds{destination_queue, transport}` - Time to send to queue

### Size and State

- `asya_actor_message_size_bytes{direction}` - Message size in bytes (direction: received, sent)
- `asya_actor_active_messages` - Currently processing messages (gauge)
- `asya_actor_runtime_errors_total{queue, error_type}` - Runtime errors by type

### Queue Depth (from KEDA)

- `keda_scaler_metrics_value{scaledObject}` - Current queue depth (exposed by KEDA, not Asya)
- `keda_scaler_active{scaledObject}` - Active scalers (1=active, 0=inactive)

### Autoscaling (from kube-state-metrics)

- `kube_horizontalpodautoscaler_status_current_replicas` - Current pod count
- `kube_horizontalpodautoscaler_status_desired_replicas` - Desired pod count

### Custom Metrics

Configurable via `ASYA_CUSTOM_METRICS` environment variable (JSON array). See [Sidecar documentation](../reference/components/core-sidecar.md) for details.

## Prometheus Configuration

Sidecar exposes metrics on `:8080/metrics` (configurable via `ASYA_METRICS_ADDR`).

### ServiceMonitor (Prometheus Operator)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: asya-actors
spec:
  selector:
    matchLabels:
      asya.sh/actor: "*"  # Matches all AsyncActors
  endpoints:
  - port: metrics
    path: /metrics
    interval: 30s
```

### Scrape Config (Standard Prometheus)

```yaml
scrape_configs:

- job_name: asya-actors
  kubernetes_sd_configs:
  - role: pod
  relabel_configs:
  - source_labels: [__meta_kubernetes_pod_label_asya_sh_actor]
    action: keep
    regex: .+
  - source_labels: [__meta_kubernetes_pod_container_name]
    action: keep
    regex: asya-sidecar
  - source_labels: [__address__]
    action: replace
    regex: ([^:]+)(?::\d+)?
    replacement: $1:8080
    target_label: __address__
```

**Note**: Operator does NOT automatically create ServiceMonitors. You must configure Prometheus scraping manually.

## Grafana Dashboards

### Example Queries

**Actor throughput** (messages per second):
```promql
rate(asya_actor_messages_processed_total{queue="asya-my-actor"}[5m])
```

**P95 processing latency**:
```promql
histogram_quantile(0.95, rate(asya_actor_processing_duration_seconds_bucket{queue="asya-my-actor"}[5m]))
```

**P95 runtime latency** (handler execution only):
```promql
histogram_quantile(0.95, rate(asya_actor_runtime_execution_duration_seconds_bucket{queue="asya-my-actor"}[5m]))
```

**Error rate** (errors per second):
```promql
rate(asya_actor_messages_failed_total{queue="asya-my-actor"}[5m])
```

**Error rate by reason**:
```promql
sum by (reason) (rate(asya_actor_messages_failed_total{queue="asya-my-actor"}[5m]))
```

**Queue depth** (from KEDA):
```promql
keda_scaler_metrics_value{scaledObject="my-actor"}
```

**Active replicas vs desired**:
```promql
kube_horizontalpodautoscaler_status_current_replicas{horizontalpodautoscaler="my-actor"}
kube_horizontalpodautoscaler_status_desired_replicas{horizontalpodautoscaler="my-actor"}
```

**Messages in flight**:
```promql
asya_actor_active_messages{queue="asya-my-actor"}
```

## Alerting

### Example Prometheus Alerts

**High error rate**:
```yaml
- alert: AsyaActorHighErrorRate
  expr: |
    (
      rate(asya_actor_messages_failed_total{queue=~"asya-.*"}[5m])
      /
      rate(asya_actor_messages_received_total{queue=~"asya-.*"}[5m])
    ) > 0.1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High error rate for queue {{ $labels.queue }}"
    description: "Error rate is {{ $value | humanizePercentage }} (threshold: 10%)"
```

**Queue backing up**:
```yaml
- alert: AsyaQueueBackingUp
  expr: keda_scaler_metrics_value{scaledObject=~".*"} > 1000
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Queue {{ $labels.scaledObject }} depth exceeds 1000 messages"
    description: "Current queue depth: {{ $value }}"
```

**Actor scaling to max**:
```yaml
- alert: AsyaActorAtMaxReplicas
  expr: |
    kube_horizontalpodautoscaler_status_current_replicas
    ==
    kube_horizontalpodautoscaler_spec_max_replicas
  for: 15m
  labels:
    severity: info
  annotations:
    summary: "Actor {{ $labels.horizontalpodautoscaler }} at max replicas"
    description: "Consider increasing maxReplicaCount if queue continues to grow"
```

**High processing latency**:
```yaml
- alert: AsyaHighLatency
  expr: |
    histogram_quantile(0.95,
      rate(asya_actor_processing_duration_seconds_bucket{queue=~"asya-.*"}[5m])
    ) > 60
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "High P95 latency for queue {{ $labels.queue }}"
    description: "P95 latency is {{ $value }}s (threshold: 60s)"
```

**Runtime errors**:
```yaml
- alert: AsyaRuntimeErrors
  expr: rate(asya_actor_runtime_errors_total{queue=~"asya-.*"}[5m]) > 0.01
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Runtime errors detected for queue {{ $labels.queue }}"
    description: "Error rate: {{ $value }} errors/second"
```

## Gateway Metrics

Gateway does NOT currently expose Prometheus metrics. Available operational data:

- **Structured JSON logs** — request/response logging with trace context
- **PostgreSQL task state** — query `tasks` table for status, timestamps, error details
- **Health endpoint** — `GET /health` for liveness/readiness probes

Prometheus metric instrumentation is planned as a future enhancement.

## Operator Metrics

Exposed via controller-runtime:

- `controller_runtime_reconcile_total{controller="asyncactor"}` - Total reconciliations
- `controller_runtime_reconcile_errors_total{controller="asyncactor"}` - Failed reconciliations
- `controller_runtime_reconcile_time_seconds{controller="asyncactor"}` - Reconciliation duration

## Distributed Tracing

### Configuration

Set `OTEL_EXPORTER_OTLP_ENDPOINT` on sidecar and gateway to enable tracing. Both gRPC
(default) and HTTP/protobuf transports are supported, selected by `OTEL_EXPORTER_OTLP_PROTOCOL`.

The endpoint format depends on the protocol:
- **gRPC** (default, port 4317): bare `host:port` — e.g. `tempo:4317`
- **HTTP/protobuf** (port 4318): full URL — e.g. `http://tempo:4318`

**Sidecar (per-actor)**:
```yaml
spec:
  tracing:
    endpoint: "tempo:4317"      # or "http://tempo:4318" for HTTP
    protocol: ""                # omit or "grpc" for gRPC; "http" for HTTP/protobuf
```

**Gateway** (Helm values):
```yaml
tracing:
  endpoint: "tempo:4317"
  protocol: ""                  # omit or "grpc" for gRPC; "http" for HTTP/protobuf
```

**Crossplane chart** (cluster-wide sidecar default):
```yaml
sidecar:
  tracingEndpoint: "tempo:4317"
  tracingProtocol: ""           # omit or "grpc" for gRPC; "http" for HTTP/protobuf
```

### Playground Setup

Enable `sampleTracing.enabled: true` in the playground chart to deploy Grafana
Tempo. The Tempo datasource is auto-provisioned in Grafana.

### Querying Traces

In Grafana Explore, select the Tempo datasource and use TraceQL:

```
{resource.service.name="my-actor"}
{span.asya.actor="text-processor" && status=error}
```

## Logging

Use standard Kubernetes logging tools:

- Fluentd
- Loki
- CloudWatch (AWS)

**Structured logs** in JSON format for easy parsing:

```json
{
  "level": "info",
  "msg": "Processing message",
  "message_id": "5e6fdb2d-1d6b-4e91-baef-73e825434e7b",
  "actor": "text-processor",
  "timestamp": "2025-11-18T12:00:00Z"
}
```
