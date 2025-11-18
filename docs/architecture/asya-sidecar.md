# Asya Sidecar

Go-based message routing service between async queues and actor runtimes.

## Responsibilities

- **Message routing**: Consume from queues, route to runtime, send to next queue
- **Transport management**: Abstract RabbitMQ, SQS differences via pluggable interface
- **Observability**: Emit Prometheus metrics, structured logs for monitoring
- **Reliability**: Handle retries, timeouts, error routing, gateway health checks
- **Progress tracking**: Report three-point progress (received, processing, completed) to gateway

## Design Principles

- **Transport Agnostic**: Pluggable interface for multiple queue systems
- **Simple Protocol**: JSON over Unix sockets
- **Fault Tolerant**: NACK retry, timeout handling
- **Stateless**: No shared state between messages
- **Observable**: Structured logging

## Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Asya🎭 Actor Sidecar                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────┐     ┌──────────┐     ┌─────────────────┐      │
│  │ Config   │────▶│ Main     │────▶│ Router          │      │
│  └──────────┘     └──────────┘     └────────┬────────┘      │
│                                             │               │
│                   ┌─────────────────────────┼               │
│                   │                         │               │
│                   ▼                         ▼               │
│           ┌──────────────┐         ┌──────────────────┐     │
│           │  Transport   │         │ Runtime Client   │     │
│           │  Interface   │         └──────────────────┘     │
│           └──────┬───────┘                 │                │
│                  │                         │                │
│         ┌────────┴────────┐                │                │
│         │                 │                │                │
│         ▼                 ▼                ▼                │
│  ┌─────────────┐   ┌─────────────┐   ┌──────────┐           │
│  │ RabbitMQ    │   │ Runtime     │   │ Metrics  │           │
│  │ Transport   │   │ Client      │   │ Server   │           │
│  └─────────────┘   └─────────────┘   └──────────┘           │
│         │                 │                │                │
└─────────┼─────────────────┼────────────────┼────────────────┘
          │                 │                │
          ▼                 ▼                ▼
    ┌──────────┐      ┌─────────────┐    ┌──────────┐
    │ RabbitMQ │      │   Actor     │    │Prometheus│
    │ Queues   │      │  Runtime    │    │  / Other │
    └──────────┘      └─────────────┘    └──────────┘
```

## How It Works

1. Wait for runtime ready signal (`/var/run/asya/runtime-ready` file + socket verification)
2. Check gateway health if `ASYA_GATEWAY_URL` configured
3. Consume message from actor's queue (`asya-{actor_name}`)
4. Parse and validate envelope structure (ID required)
5. Report progress: "received" status to gateway
6. Verify route matches actor name
7. Report progress: "processing" status to gateway
8. Forward to runtime via Unix socket with timeout
9. Receive response(s) from runtime (single or fan-out)
10. Report progress: "completed" status to gateway (for first response)
11. Route response(s) to next actor or end queue
12. Ack message on success, nack on routing failures

## Communication with Runtime

**Protocol**: Unix domain socket with length-prefix framing

**Socket path**: `/var/run/asya/asya-runtime.sock` (configurable via `ASYA_SOCKET_DIR`)

**Timeout**: Enforced by sidecar (default: 5 minutes via `ASYA_RUNTIME_TIMEOUT`)

**See**: [protocols/sidecar-runtime.md](protocols/sidecar-runtime.md) for details.

## Deployment

Injected automatically by operator into actor pods:

```yaml
containers:
- name: asya-sidecar
  image: asya-sidecar:latest
  env:
  - name: ASYA_ACTOR_NAME
    value: text-processor
  - name: ASYA_TRANSPORT
    value: sqs
  - name: ASYA_GATEWAY_URL
    value: http://asya-gateway:80
  volumeMounts:
  - name: socket-dir
    mountPath: /var/run/asya
```

## Error Handling

### Sidecar Errors (Nack)

If sidecar crashes or encounters routing failures:
- Message nacked, requeued by transport
- After max retries → DLQ (configured by queue)

### Runtime Errors (Ack + Route to error-end)

If runtime returns error response:
- Message acked (removed from queue)
- Error envelope created with error details (message, type, traceback)
- Envelope sent to `asya-error-end` queue
- `error-end` crew actor handles retry logic

### Timeout (Send to error-end + Exit)

If runtime exceeds timeout (`ASYA_RUNTIME_TIMEOUT`, default 5m):
- Sidecar sends timeout error envelope to `asya-error-end` queue
- Reports final error to gateway (if configured)
- **Pod crashes with `os.Exit(1)`** to prevent zombie processing
- Kubernetes restarts pod for recovery

**IMPORTANT**: Timeout crashes are intentional - runtime may still be processing, so pod must restart to recover.

### Validation Errors (Parse/Missing ID)

If envelope fails parsing or missing required `id` field:
- Invalid envelope sent to `asya-error-end` queue with error details
- Message acked (removed from queue)

### Route Mismatch

If envelope routed to wrong actor:
- Error sent to `asya-error-end` queue
- Message acked
- Logged as `route_mismatch` metric

## Routing Logic

### Normal Flow

1. Sidecar sends envelope to runtime via Unix socket
2. Runtime processes and increments `route.current` (automatically in payload mode, manually in envelope mode)
3. Runtime returns response with updated route
4. Sidecar determines destination: `route.actors[route.current]` or `happy-end` if no more actors
5. Sidecar creates new envelope with same ID (or `{id}-{index}` for fan-out children)
6. Sidecar sends envelope to destination queue (`asya-{actor_name}`)

### End of Route

When `route.current >= len(route.actors)` (no more actors):
- Sidecar automatically routes to `asya-happy-end` queue
- **NEVER** configure `happy-end` in route manually

### Empty Response

When runtime returns `null`, `[]`, or zero-length array:
- Sidecar routes envelope to `asya-happy-end` queue (abort pipeline)
- Used for conditional processing or early termination

### Error Response

When runtime returns error object with `"error"` field:
- Sidecar routes to `asya-error-end` queue
- **NEVER** configure `error-end` in route manually

### Fan-Out (Multiple Responses)

When runtime returns array with multiple payloads:
- First response keeps original envelope ID
- Subsequent responses get suffixed IDs: `{original_id}-1`, `{original_id}-2`, etc.
- Each fanout child is created in gateway via `POST /envelopes`
- All fanout envelopes share same route state after runtime processing

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_ACTOR_NAME` | (required) | Actor name (for queue naming: `asya-{actor_name}`) |
| `ASYA_TRANSPORT` | `rabbitmq` | Transport type: `sqs`, `rabbitmq` |
| `ASYA_RUNTIME_TIMEOUT` | `5m` | Processing timeout per message (Go duration format) |
| `ASYA_SOCKET_DIR` | `/var/run/asya` | Unix socket directory (internal testing only - DO NOT set in production) |
| `ASYA_GATEWAY_URL` | - | Gateway URL for progress/status reporting |
| `ASYA_ACTOR_HAPPY_END` | `happy-end` | Happy-end actor name (for queue resolution) |
| `ASYA_ACTOR_ERROR_END` | `error-end` | Error-end actor name (for queue resolution) |
| `ASYA_IS_END_ACTOR` | `false` | End actor mode (no routing, only final status reporting) |
| `ASYA_LOG_LEVEL` | `INFO` | Logging level: `DEBUG`, `INFO`, `WARN`, `ERROR` |
| `ASYA_RUNTIME_READY_TIMEOUT` | `5m` | Max wait time for runtime ready signal |

### Transport-Specific Configuration

**RabbitMQ**:
| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_RABBITMQ_URL` | - | Full RabbitMQ URL (overrides host/port/user/pass) |
| `ASYA_RABBITMQ_HOST` | `localhost` | RabbitMQ host |
| `ASYA_RABBITMQ_PORT` | `5672` | RabbitMQ port |
| `ASYA_RABBITMQ_USERNAME` | `guest` | RabbitMQ username |
| `ASYA_RABBITMQ_PASSWORD` | `guest` | RabbitMQ password |
| `ASYA_RABBITMQ_EXCHANGE` | `asya` | RabbitMQ exchange name |
| `ASYA_RABBITMQ_PREFETCH` | `1` | Prefetch count (QoS) |

**SQS**:
| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_AWS_REGION` | `us-east-1` | AWS region |
| `ASYA_SQS_ENDPOINT` | - | Custom SQS endpoint (for LocalStack) |
| `ASYA_SQS_VISIBILITY_TIMEOUT` | `0` | Visibility timeout in seconds (0 = auto-calculated as 2x `ASYA_RUNTIME_TIMEOUT`) |
| `ASYA_SQS_WAIT_TIME_SECONDS` | `20` | Long polling wait time |

**Queue Management**:
| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_QUEUE_AUTO_CREATE` | `true` | Auto-create queues if they don't exist |

### Metrics Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_METRICS_ENABLED` | `true` | Enable Prometheus metrics |
| `ASYA_METRICS_ADDR` | `:8080` | Metrics server address |
| `ASYA_METRICS_NAMESPACE` | `asya_actor` | Prometheus namespace for metrics |
| `ASYA_CUSTOM_METRICS` | - | JSON array of custom metric configurations |

All configuration injected by operator based on `spec.transport` and actor-specific settings.

## End Actor Mode

End actors (`happy-end`, `error-end`) run in special mode controlled by `ASYA_IS_END_ACTOR=true`:

**Behavior differences**:
- Accept envelopes with ANY route state (no route validation)
- Process envelope through runtime without route incrementing
- Do NOT route responses to any queue (terminal processing)
- Report final status to gateway with result or error details
- Runtime typically returns empty dict `{}` (ignored by sidecar)

**Error handling**:
- On runtime timeout: Reports final error to gateway, then crashes with `os.Exit(1)`
- On runtime error: Logs error but continues (non-fatal for end actors)

**Final status reporting**:
- `happy-end`: Reports `status: "succeeded"` with result payload
- `error-end`: Reports `status: "failed"` with error details and actor information

**See**: [asya-crew.md](asya-crew.md) for end actor implementations.

## Progress Reporting

When `ASYA_GATEWAY_URL` is configured, sidecar reports three-point progress for each envelope:

1. **Received** (`status: "received"`):
   - Sent when envelope pulled from queue
   - Includes envelope size in KB

2. **Processing** (`status: "processing"`):
   - Sent before forwarding to runtime
   - Includes current actor name

3. **Completed** (`status: "completed"`):
   - Sent after runtime returns (only for first response in fan-out)
   - Includes processing duration in milliseconds

**Progress payload**:
```json
{
  "actors": ["preprocess", "infer", "post"],
  "current_actor_idx": 0,
  "status": "received",
  "message": "Received message (1.23 KB)",
  "message_size_kb": 1.23
}
```

**Retry logic**: Progress reporting retries up to 5 times with 200ms delay. Failures logged but do not block envelope processing.

**Gateway health check**: On startup, sidecar verifies gateway reachability via `GET /health`. Startup fails if gateway configured but unreachable.

## Metrics

Sidecar exposes Prometheus metrics on `:8080/metrics` (configurable via `ASYA_METRICS_ADDR`):

### Standard Metrics

**Message Counters**:
- `{namespace}_messages_received_total{queue, transport}` - Messages received from queue
- `{namespace}_messages_processed_total{queue, status}` - Messages successfully processed (status: `success`, `empty_response`, `end_consumed`)
- `{namespace}_messages_sent_total{destination_queue, message_type}` - Messages sent to queues (message_type: `routing`, `happy_end`, `error_end`)
- `{namespace}_messages_failed_total{queue, reason}` - Failed messages (reason: `parse_error`, `runtime_error`, `transport_error`, `validation_error`, `route_mismatch`, `error_queue_send_failed`)

**Duration Histograms**:
- `{namespace}_processing_duration_seconds{queue}` - Total processing time (queue receive → queue send)
- `{namespace}_runtime_execution_duration_seconds{queue}` - Runtime execution time only
- `{namespace}_queue_receive_duration_seconds{queue, transport}` - Time to receive from queue
- `{namespace}_queue_send_duration_seconds{destination_queue, transport}` - Time to send to queue

**Size Metrics**:
- `{namespace}_envelope_size_bytes{direction}` - Envelope size in bytes (direction: `received`, `sent`)

**Other**:
- `{namespace}_active_messages` - Currently processing messages (gauge)
- `{namespace}_runtime_errors_total{queue, error_type}` - Runtime errors by type (error_type: `execution_error`)

Default namespace: `asya_actor` (configurable via `ASYA_METRICS_NAMESPACE`)

### Custom Metrics

Actors can define custom metrics via `ASYA_CUSTOM_METRICS` JSON configuration. Supported types:
- **Counter**: Monotonically increasing value
- **Gauge**: Value that can go up or down
- **Histogram**: Distribution of values with configurable buckets

Example custom metrics configuration:
```json
[
  {
    "name": "model_predictions_total",
    "type": "counter",
    "help": "Total model predictions",
    "labels": ["model_version"]
  },
  {
    "name": "model_confidence",
    "type": "histogram",
    "help": "Model confidence scores",
    "labels": ["model_version"],
    "buckets": [0.5, 0.7, 0.8, 0.9, 0.95, 0.99]
  }
]
```

**See**: [observability.md](observability.md) for monitoring setup and alerting.
