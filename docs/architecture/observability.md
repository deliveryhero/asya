# Observability

## Built-in Metrics

Asya components expose Prometheus metrics.

### Sidecar Metrics

Default namespace: `asya_actor` (configurable via `ASYA_METRICS_NAMESPACE`)

**Message Counters**:

- `{namespace}_messages_received_total{queue, transport}` - Messages received from queue
- `{namespace}_messages_processed_total{queue, status}` - Successfully processed (status: success, empty_response, end_consumed)
- `{namespace}_messages_sent_total{destination_queue, message_type}` - Messages sent to queues (message_type: routing, happy_end, error_end)
- `{namespace}_messages_failed_total{queue, reason}` - Failed messages (reason: parse_error, runtime_error, transport_error, validation_error, route_mismatch, error_queue_send_failed)

**Duration Histograms**:

- `{namespace}_processing_duration_seconds{queue}` - Total processing time (queue receive → queue send)
- `{namespace}_runtime_execution_duration_seconds{queue}` - Runtime execution time only
- `{namespace}_queue_receive_duration_seconds{queue, transport}` - Time to receive from queue
- `{namespace}_queue_send_duration_seconds{destination_queue, transport}` - Time to send to queue

**Size Metrics**:

- `{namespace}_envelope_size_bytes{direction}` - Envelope size in bytes (direction: received, sent)

**Other**:

- `{namespace}_active_messages` - Currently processing messages (gauge)
- `{namespace}_runtime_errors_total{queue, error_type}` - Runtime errors by type

**Custom Metrics**: Configurable via `ASYA_CUSTOM_METRICS` environment variable (JSON array). See [asya-sidecar.md](asya-sidecar.md#metrics-and-observability) for details.

### Runtime Metrics

Runtime does NOT expose Prometheus metrics. All metrics are collected by sidecar.

### Operator Metrics
Exposed via controller-runtime:

- `controller_runtime_reconcile_total{controller="asyncactor"}` - Total reconciliations
- `controller_runtime_reconcile_errors_total{controller="asyncactor"}` - Failed reconciliations
- `controller_runtime_reconcile_time_seconds{controller="asyncactor"}` - Reconciliation duration

### Gateway Metrics

Gateway does NOT currently expose Prometheus metrics. This is a future enhancement.

## Integration with Prometheus

Sidecar exposes metrics on `:8080/metrics` (configurable via `ASYA_METRICS_ADDR`).

**Scraping configuration** (Prometheus):
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

**ServiceMonitor** (Prometheus Operator):
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

**Note**: Operator does NOT automatically create ServiceMonitors. Users must configure Prometheus scraping manually.

## Integration with Grafana

**Example dashboards** (future):

- Actor performance (throughput, latency, errors)
- Queue depth and autoscaling
- Resource usage (CPU, memory, GPU)
- Error rates and types

## Logging

**Structured logging** with JSON format:

```json
{
  "level": "info",
  "msg": "Processing envelope",
  "envelope_id": "5e6fdb2d-1d6b-4e91-baef-73e825434e7b",
  "actor": "text-processor",
  "timestamp": "2025-11-18T12:00:00Z"
}
```

**Log aggregation**: Use standard Kubernetes logging (Fluentd, Loki, CloudWatch).

## Tracing (Future)

**OpenTelemetry tracing** for distributed request tracing:

- Trace envelopes across actors
- Visualize pipeline execution
- Identify bottlenecks

Currently not implemented.
