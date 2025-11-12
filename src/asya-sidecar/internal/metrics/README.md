# Asya🎭 Sidecar Metrics

Prometheus metrics implementation for the Asya🎭 sidecar.

## Endpoints

- `/metrics` - Prometheus metrics endpoint (OpenMetrics format)
- `/health` - Health check endpoint (returns 200 OK)

## Standard Metrics

### Counters

| Metric | Labels | Description |
|--------|--------|-------------|
| `messages_received_total` | `queue`, `transport` | Total messages received from queue |
| `messages_processed_total` | `queue`, `status` | Total messages successfully processed<br/>Status: `success`, `error`, `empty_response` |
| `messages_sent_total` | `destination_queue`, `message_type` | Total messages sent to queues<br/>Type: `routing`, `happy_end`, `error_end` |
| `messages_failed_total` | `queue`, `reason` | Total failed messages<br/>Reason: `parse_error`, `runtime_error`, `transport_error` |
| `runtime_errors_total` | `queue`, `error_type` | Total runtime errors by type |

### Gauges

| Metric | Labels | Description |
|--------|--------|-------------|
| `active_messages` | - | Number of messages currently being processed |

### Histograms

| Metric | Labels | Buckets | Description |
|--------|--------|---------|-------------|
| `processing_duration_seconds` | `queue` | 0.005 to 120s | Total time to process a message (queue receive to queue send) |
| `runtime_execution_duration_seconds` | `queue` | 0.005 to 120s | Time spent executing payload in runtime |
| `queue_receive_duration_seconds` | `queue`, `transport` | 0.001 to 10s | Time spent receiving message from queue |
| `queue_send_duration_seconds` | `destination_queue`, `transport` | 0.001 to 5s | Time spent sending message to queue |
| `envelope_size_bytes` | `direction` | 100B to ~10MB (exponential) | Envelope size in bytes<br/>Direction: `received`, `sent` |

## Custom Metrics

Custom metrics can be dynamically registered via configuration. Supported types:

### Counter
```go
m.IncrementCustomCounter("my_counter", "label1", "label2")
m.AddCustomCounter("my_counter", 5.0, "label1", "label2")
```

### Gauge
```go
m.SetCustomGauge("my_gauge", 42.0, "label1")
m.IncrementCustomGauge("my_gauge", "label1")
m.DecrementCustomGauge("my_gauge", "label1")
```

### Histogram
```go
m.ObserveCustomHistogram("my_histogram", 1.23, "label1")
```

## Configuration

Metrics are initialized via `NewMetrics(namespace, customMetricsConfig)`:

- `namespace`: Prometheus namespace prefix for all metrics
- `customMetricsConfig`: Array of custom metric configurations from `config.CustomMetricConfig`

## Starting the Metrics Server

```go
err := metrics.StartMetricsServer(ctx, ":9090")
```

The server runs until the context is cancelled, with graceful shutdown (5s timeout).
