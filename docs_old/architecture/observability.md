# Metrics Reference

Prometheus metrics exposed by Asya🎭 components.

> **Sidecar Metrics**: [`src/asya-sidecar/METRICS.md`](/src/asya-sidecar/METRICS.md)

## Sidecar Metrics

### Message Flow Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `asya_actor_messages_received_total` | Counter | `queue`, `transport` | Total messages received from queue |
| `asya_actor_messages_processed_total` | Counter | `queue`, `status` | Total messages processed (status: success, error, empty_response) |
| `asya_actor_messages_sent_total` | Counter | `destination_queue`, `message_type` | Total messages sent to queues |
| `asya_actor_messages_failed_total` | Counter | `queue`, `reason` | Total failed messages |
| `asya_actor_active_messages` | Gauge | - | Number of messages currently being processed |

### Performance Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `asya_actor_processing_duration_seconds` | Histogram | `queue` | Total message processing time |
| `asya_actor_runtime_execution_duration_seconds` | Histogram | `queue` | Time spent in runtime |
| `asya_actor_queue_receive_duration_seconds` | Histogram | `queue`, `transport` | Time spent receiving from queue |
| `asya_actor_queue_send_duration_seconds` | Histogram | `destination_queue`, `transport` | Time spent sending to queue |
| `asya_actor_message_size_bytes` | Histogram | `direction` | Message size (direction: received, sent) |

### Error Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `asya_actor_runtime_errors_total` | Counter | `queue`, `error_type` | Total runtime errors by type |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_METRICS_ENABLED` | `true` | Enable/disable metrics |
| `ASYA_METRICS_ADDR` | `:8080` | Metrics server address |
| `ASYA_METRICS_NAMESPACE` | `asya_actor` | Prometheus namespace |

### Accessing Metrics

**Metrics endpoint:**
```
http://pod-ip:8080/metrics
```

**Health endpoint:**
```
http://pod-ip:8080/health
```

## Prometheus Configuration

### Scrape Config

```yaml
scrape_configs:
  - job_name: 'asya-crew'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: (.+)
        replacement: ${1}:8080
```

### Pod Annotations

```yaml
apiVersion: v1
kind: Pod
metadata:
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "8080"
    prometheus.io/path: "/metrics"
```

## Grafana Dashboards

### Useful Queries

**Message throughput:**
```promql
rate(asya_actor_messages_processed_total[5m])
```

**Success rate:**
```promql
rate(asya_actor_messages_processed_total{status="success"}[5m])
/
rate(asya_actor_messages_processed_total[5m])
```

**Average processing time:**
```promql
rate(asya_actor_processing_duration_seconds_sum[5m])
/
rate(asya_actor_processing_duration_seconds_count[5m])
```

**P95 processing latency:**
```promql
histogram_quantile(0.95, rate(asya_actor_processing_duration_seconds_bucket[5m]))
```

**P99 processing latency:**
```promql
histogram_quantile(0.99, rate(asya_actor_processing_duration_seconds_bucket[5m]))
```

**Active messages:**
```promql
asya_actor_active_messages
```

**Error rate:**
```promql
rate(asya_actor_messages_failed_total[5m])
```

**Queue depth by destination:**
```promql
sum by (destination_queue) (rate(asya_actor_messages_sent_total[5m]))
```

## Custom Metrics

You can define custom AI/ML metrics. See [`src/asya-sidecar/METRICS.md`](/src/asya-sidecar/METRICS.md) for details on custom metric configuration.

**Example AI metrics:**
```bash
export ASYA_CUSTOM_METRICS='[
  {
    "name": "ai_tokens_processed_total",
    "type": "counter",
    "help": "Total tokens processed",
    "labels": ["model", "operation"]
  },
  {
    "name": "ai_inference_duration_seconds",
    "type": "histogram",
    "help": "Inference time",
    "labels": ["model"],
    "buckets": [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
  }
]'
```

## Next Steps

- [Sidecar Metrics Documentation](/src/asya-sidecar/METRICS.md) - Detailed metrics guide
- [Architecture Overview](README.md) - Observability architecture
- [Deployment Guide](../guides/deploy.md) - Monitoring setup
