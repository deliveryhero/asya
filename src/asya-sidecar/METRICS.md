# Sidecar Metrics

> Full metrics implementation: [internal/metrics/README.md](internal/metrics/README.md)

The sidecar exposes Prometheus-compatible metrics for monitoring actor performance.

## Standard Metrics

### Envelope Flow

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `asya_actor_messages_received_total` | Counter | `queue`, `transport` | Messages received from queue |
| `asya_actor_messages_processed_total` | Counter | `queue`, `status` | Messages processed (status: success, error, empty_response) |
| `asya_actor_messages_sent_total` | Counter | `destination_queue`, `message_type` | Messages sent (type: routing, happy_end, error_end) |
| `asya_actor_messages_failed_total` | Counter | `queue`, `reason` | Failed messages (reason: parse_error, runtime_error, routing_error) |
| `asya_actor_active_messages` | Gauge | - | Messages currently being processed |

### Performance

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `asya_actor_processing_duration_seconds` | Histogram | `queue` | Total message processing time (queue receive → send) |
| `asya_actor_runtime_execution_duration_seconds` | Histogram | `queue` | Runtime execution time |
| `asya_actor_queue_receive_duration_seconds` | Histogram | `queue`, `transport` | Queue receive time |
| `asya_actor_queue_send_duration_seconds` | Histogram | `destination_queue`, `transport` | Queue send time |
| `asya_actor_envelope_size_bytes` | Histogram | `direction` | Envelope size (direction: received, sent) |

### Errors

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `asya_actor_runtime_errors_total` | Counter | `queue`, `error_type` | Runtime errors by type |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_METRICS_ENABLED` | `true` | Enable/disable metrics |
| `ASYA_METRICS_ADDR` | `:8080` | Metrics server address |
| `ASYA_METRICS_NAMESPACE` | `asya_actor` | Prometheus namespace |
| `ASYA_CUSTOM_METRICS` | `""` | JSON array of custom metrics |

### Examples

```bash
# Change metrics port
export ASYA_METRICS_ADDR=":9090"

# Custom namespace
export ASYA_METRICS_NAMESPACE="my_app"

# Disable metrics
export ASYA_METRICS_ENABLED=false
```

## Custom Metrics (AI/ML)

Define custom metrics via `ASYA_CUSTOM_METRICS`:

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
    "help": "Inference duration",
    "labels": ["model"],
    "buckets": [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
  },
  {
    "name": "ai_prompt_tokens",
    "type": "histogram",
    "help": "Prompt token count",
    "labels": ["model"],
    "buckets": [10, 50, 100, 500, 1000, 5000]
  }
]'
```

**Supported types**: `counter`, `gauge`, `histogram`

See [internal/metrics/README.md](internal/metrics/README.md) for implementation details.

## Accessing Metrics

```bash
# Metrics endpoint
curl http://localhost:8080/metrics

# Health check
curl http://localhost:8080/health
```

**Sample output**:
```
asya_actor_messages_received_total{queue="text-processing",transport="rabbitmq"} 1523
asya_actor_processing_duration_seconds_sum{queue="text-processing"} 342.5
asya_actor_processing_duration_seconds_count{queue="text-processing"} 1523
```

## Prometheus Setup

See [Deployment Guide](../../docs/guides/deploy.md#monitoring) for Prometheus/Grafana setup.

### Pod Annotations

```yaml
metadata:
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "8080"
    prometheus.io/path: "/metrics"
spec:
  containers:
  - name: sidecar
    env:
    - name: ASYA_METRICS_ENABLED
      value: "true"
    ports:
    - name: metrics
      containerPort: 8080
```

## Example Queries

```promql
# Envelope throughput
rate(asya_actor_messages_processed_total[5m])

# Success rate
rate(asya_actor_messages_processed_total{status="success"}[5m])
/
rate(asya_actor_messages_processed_total[5m])

# P95 latency
histogram_quantile(0.95, rate(asya_actor_processing_duration_seconds_bucket[5m]))

# Error rate
rate(asya_actor_messages_failed_total[5m])
```

## Best Practices

1. **Histogram buckets**: Match expected value ranges
2. **Label cardinality**: Avoid high-cardinality values (UUIDs, timestamps)
3. **Metric types**:
   - Counters: Monotonically increasing (never decrement)
   - Gauges: Current values (can go up/down)
   - Histograms: Value distributions

## Troubleshooting

**Metrics not appearing**:
```bash
curl http://localhost:8080/metrics
```

Check:
- `ASYA_METRICS_ENABLED=true`
- Port matches `ASYA_METRICS_ADDR`
- Firewall allows port

**Custom metrics not registered**:
```bash
# Validate JSON
echo $ASYA_CUSTOM_METRICS | jq .

# Check logs
grep "Registered custom" <sidecar-logs>
```
