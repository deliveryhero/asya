# Monitoring

Observability and monitoring for Asya🎭 deployments.

## Overview

Asya components expose OpenTelemetry metrics for Prometheus scraping.

**See**: [../architecture/observability.md](../architecture/observability.md) for complete metrics reference.

## Key Metrics

### Actor Performance

- `asya_sidecar_processing_duration_seconds` - Processing time per message
- `asya_sidecar_messages_processed_total` - Total messages processed
- `asya_runtime_requests_total{error_code}` - Handler invocations by status

### Queue Depth

- `keda_scaler_metrics_value{scaledObject}` - Current queue depth
- `keda_scaler_active` - Active scalers

### Autoscaling

- `kube_hpa_status_current_replicas` - Current pod count
- `kube_hpa_status_desired_replicas` - Desired pod count

### Errors

- `asya_sidecar_errors_total{type}` - Sidecar errors by type
- `asya_sidecar_timeouts_total` - Timeout events
- `asya_runtime_oom_total{type}` - OOM events

## Prometheus Configuration

**ServiceMonitor example**:
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

## Grafana Dashboards

**Example queries**:

**Actor throughput**:
```promql
rate(asya_sidecar_messages_processed_total{actor="my-actor"}[5m])
```

**P95 latency**:
```promql
histogram_quantile(0.95, rate(asya_sidecar_processing_duration_seconds_bucket[5m]))
```

**Error rate**:
```promql
rate(asya_sidecar_errors_total[5m])
```

**Queue depth**:
```promql
keda_scaler_metrics_value{scaledObject="my-actor"}
```

## Alerting

**Example alerts**:

**High error rate**:
```yaml
- alert: HighErrorRate
  expr: rate(asya_sidecar_errors_total[5m]) > 0.1
  for: 5m
  annotations:
    summary: "High error rate for actor {{ $labels.actor }}"
```

**Queue backing up**:
```yaml
- alert: QueueBackingUp
  expr: keda_scaler_metrics_value > 1000
  for: 10m
  annotations:
    summary: "Queue {{ $labels.scaledObject }} depth > 1000"
```

**OOM events**:
```yaml
- alert: FrequentOOM
  expr: rate(asya_runtime_oom_total[10m]) > 0.01
  annotations:
    summary: "Frequent OOM for actor {{ $labels.actor }}"
```

## Logging

Use standard Kubernetes logging tools:
- Fluentd
- Loki
- CloudWatch (AWS)

**Structured logs** in JSON format for easy parsing.

## Future

- OpenTelemetry tracing for distributed request tracing
- Pre-built Grafana dashboards
