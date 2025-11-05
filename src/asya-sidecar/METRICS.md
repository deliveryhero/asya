# Asya Sidecar Metrics

The asya-sidecar exposes Prometheus-compatible metrics for monitoring actor performance and health.

## Standard Metrics

The sidecar automatically exposes these standard metrics:

### Message Flow Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `asya_actor_messages_received_total` | Counter | `queue`, `transport` | Total messages received from queue |
| `asya_actor_messages_processed_total` | Counter | `queue`, `status` | Total messages processed (status: success, error, empty_response) |
| `asya_actor_messages_sent_total` | Counter | `destination_queue`, `message_type` | Total messages sent to queues (type: routing, happy_end, error_end) |
| `asya_actor_messages_failed_total` | Counter | `queue`, `reason` | Total failed messages (reason: parse_error, runtime_error, routing_error) |
| `asya_actor_active_messages` | Gauge | - | Number of messages currently being processed |

### Performance Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `asya_actor_processing_duration_seconds` | Histogram | `queue` | Total message processing time (queue receive to queue send) |
| `asya_actor_runtime_execution_duration_seconds` | Histogram | `queue` | Time spent executing payload in runtime |
| `asya_actor_queue_receive_duration_seconds` | Histogram | `queue`, `transport` | Time spent receiving message from queue |
| `asya_actor_queue_send_duration_seconds` | Histogram | `destination_queue`, `transport` | Time spent sending message to queue |
| `asya_actor_message_size_bytes` | Histogram | `direction` | Message size in bytes (direction: received, sent) |

### Error Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `asya_actor_runtime_errors_total` | Counter | `queue`, `error_type` | Total runtime errors by type |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_METRICS_ENABLED` | `true` | Enable/disable metrics collection |
| `ASYA_METRICS_ADDR` | `:8080` | Metrics server address and port |
| `ASYA_METRICS_NAMESPACE` | `asya_actor` | Prometheus namespace for metrics |
| `ASYA_CUSTOM_METRICS` | `""` | JSON array of custom metric definitions |

### Enable/Disable Metrics

```bash
# Enable metrics (default)
export ASYA_METRICS_ENABLED=true

# Disable metrics
export ASYA_METRICS_ENABLED=false
```

### Change Metrics Port

```bash
export ASYA_METRICS_ADDR=":9090"
```

### Custom Namespace

```bash
export ASYA_METRICS_NAMESPACE="my_app"
```

## Custom Metrics

You can define custom metrics via the `ASYA_CUSTOM_METRICS` environment variable as a JSON array:

### Supported Metric Types

1. **Counter** - Monotonically increasing value (e.g., request count)
2. **Gauge** - Value that can go up or down (e.g., queue size, temperature)
3. **Histogram** - Distribution of values (e.g., request duration, payload size)

### Configuration Format

```json
[
  {
    "name": "metric_name",
    "type": "counter|gauge|histogram",
    "help": "Description of the metric",
    "labels": ["label1", "label2"],
    "buckets": [0.1, 0.5, 1, 5, 10]  // Only for histograms
  }
]
```

### Example: AI/ML Metrics

```bash
export ASYA_CUSTOM_METRICS='[
  {
    "name": "ai_tokens_processed_total",
    "type": "counter",
    "help": "Total number of tokens processed",
    "labels": ["model", "operation"]
  },
  {
    "name": "ai_model_temperature",
    "type": "gauge",
    "help": "Current model temperature setting",
    "labels": ["model"]
  },
  {
    "name": "ai_inference_duration_seconds",
    "type": "histogram",
    "help": "Time to complete inference",
    "labels": ["model"],
    "buckets": [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
  },
  {
    "name": "ai_prompt_tokens",
    "type": "histogram",
    "help": "Number of tokens in prompts",
    "labels": ["model"],
    "buckets": [10, 50, 100, 500, 1000, 5000, 10000]
  },
  {
    "name": "ai_completion_tokens",
    "type": "histogram",
    "help": "Number of tokens in completions",
    "labels": ["model"],
    "buckets": [10, 50, 100, 500, 1000, 5000, 10000]
  }
]'
```

### Updating Custom Metrics from Runtime

Your actor runtime can update custom metrics by sending special messages to the sidecar. (Implementation details depend on your socket protocol extension.)

**Planned feature:** The runtime will be able to send metric updates via the Unix socket:

```json
{
  "type": "metric_update",
  "metric": "ai_tokens_processed_total",
  "operation": "increment",
  "value": 150,
  "labels": {"model": "gpt-4", "operation": "completion"}
}
```

## Accessing Metrics

### Metrics Endpoint

Metrics are exposed at:
```
http://localhost:8080/metrics
```

### Health Endpoint

A health check endpoint is available at:
```
http://localhost:8080/health
```

### Example Queries

#### Scrape Metrics
```bash
curl http://localhost:8080/metrics
```

#### Sample Output
```
# HELP asya_actor_messages_received_total Total number of messages received from queue
# TYPE asya_actor_messages_received_total counter
asya_actor_messages_received_total{queue="text-processing",transport="rabbitmq"} 1523

# HELP asya_actor_processing_duration_seconds Total time to process a message
# TYPE asya_actor_processing_duration_seconds histogram
asya_actor_processing_duration_seconds_bucket{queue="text-processing",le="0.005"} 12
asya_actor_processing_duration_seconds_bucket{queue="text-processing",le="0.01"} 45
asya_actor_processing_duration_seconds_bucket{queue="text-processing",le="0.025"} 203
...
asya_actor_processing_duration_seconds_sum{queue="text-processing"} 342.5
asya_actor_processing_duration_seconds_count{queue="text-processing"} 1523
```

## Prometheus Configuration

Add the sidecar to your Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: 'asya-actors'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      # Only scrape pods with prometheus.io/scrape annotation
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      # Use custom port if specified
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: (.+)
        replacement: ${1}:${2}
      # Use /metrics path
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
```

## Grafana Dashboards

### Example PromQL Queries

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

**Active message count:**
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

## Kubernetes Deployment

### Pod Annotations

Add annotations to enable Prometheus scraping:

```yaml
apiVersion: v1
kind: Pod
metadata:
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "8080"
    prometheus.io/path: "/metrics"
spec:
  containers:
  - name: sidecar
    image: asya-sidecar:latest
    env:
    - name: ASYA_METRICS_ENABLED
      value: "true"
    - name: ASYA_METRICS_ADDR
      value: ":8080"
    ports:
    - name: metrics
      containerPort: 8080
      protocol: TCP
```

### Service Monitor (Prometheus Operator)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: asya-actors
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: asya-actor
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

## Example: Complete Setup with Custom Metrics

```bash
# Start sidecar with custom AI metrics
export ASYA_METRICS_ENABLED=true
export ASYA_METRICS_ADDR=":8080"
export ASYA_METRICS_NAMESPACE="ai_pipeline"
export ASYA_CUSTOM_METRICS='[
  {
    "name": "ai_model_invocations_total",
    "type": "counter",
    "help": "Total AI model invocations",
    "labels": ["model", "status"]
  },
  {
    "name": "ai_tokens_per_request",
    "type": "histogram",
    "help": "Tokens used per request",
    "labels": ["model", "type"],
    "buckets": [10, 50, 100, 500, 1000, 5000, 10000, 50000]
  },
  {
    "name": "ai_context_window_usage_ratio",
    "type": "gauge",
    "help": "Ratio of context window used (0-1)",
    "labels": ["model"]
  }
]'

./bin/sidecar
```

## Best Practices

1. **Use appropriate bucket sizes** for histograms based on your expected value ranges
2. **Limit label cardinality** - Don't use high-cardinality values (UUIDs, timestamps) as labels
3. **Namespace your metrics** - Use different namespaces for different applications
4. **Monitor metric cardinality** - Too many unique label combinations can cause memory issues
5. **Use counters for totals** - Never decrement a counter
6. **Use gauges for current values** - Temperature, queue size, etc.
7. **Use histograms for distributions** - Request durations, payload sizes, etc.

## Troubleshooting

### Metrics not appearing

Check that metrics are enabled:
```bash
curl http://localhost:8080/metrics
```

If connection refused, check:
- `ASYA_METRICS_ENABLED=true`
- `ASYA_METRICS_ADDR` matches the port you're querying
- Firewall/security groups allow the port

### Custom metrics not registered

Check sidecar logs for errors:
```
Registered custom counter: ai_tokens_processed_total
```

Validate your JSON:
```bash
echo $ASYA_CUSTOM_METRICS | jq .
```

### High memory usage

Reduce metric cardinality:
- Fewer label values
- Smaller histogram buckets
- Fewer custom metrics

## Integration with Datadog, New Relic, etc.

Most observability platforms support Prometheus metrics:

**Datadog:**
```yaml
# datadog-agent config
prometheus_scrape:
  enabled: true
  service_endpoints:
    - namespace: asya
      selector:
        app: asya-actor
```

**New Relic:**
Uses Prometheus agent mode to scrape metrics.

**Grafana Cloud:**
Configure remote write in Prometheus config.

## Future Enhancements

- [ ] OpenTelemetry traces integration
- [ ] Automatic metric updates from runtime via socket protocol
- [ ] Pre-built Grafana dashboards
- [ ] Metric aggregation across multiple actors
- [ ] Real-time metric streaming via WebSocket
