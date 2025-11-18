# Observability

## Built-in Metrics

Asya components expose OpenTelemetry metrics for Prometheus scraping.

### Sidecar Metrics

- `asya_sidecar_messages_received_total` - Messages received from queue
- `asya_sidecar_messages_processed_total` - Messages processed successfully
- `asya_sidecar_processing_duration_seconds` - Processing time histogram
- `asya_sidecar_errors_total{type}` - Error count by type
- `asya_sidecar_timeouts_total` - Timeout events

### Runtime Metrics

- `asya_runtime_requests_total{error_code}` - Handler invocations
- `asya_runtime_oom_total{type}` - OOM events (ram, cuda)
- `asya_runtime_processing_duration_seconds` - Handler execution time

### Operator Metrics

- `asya_operator_reconcile_total` - Reconciliation count
- `asya_operator_reconcile_errors_total` - Reconciliation errors
- `asya_operator_reconcile_duration_seconds` - Reconciliation time

### Gateway Metrics

- `asya_gateway_envelopes_total{status}` - Envelope count by status
- `asya_gateway_tool_calls_total{tool}` - Tool invocations
- `asya_gateway_sse_connections` - Active SSE connections

## Integration with Prometheus

**Service monitors** automatically created by operator:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: asya-sidecar
spec:
  selector:
    matchLabels:
      asya.sh/component: sidecar
  endpoints:
  - port: metrics
    interval: 30s
```

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
