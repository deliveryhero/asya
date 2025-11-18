# Asya Sidecar

## Responsibilities

- **Message routing**: Consume from queues, route to runtime, send to next queue
- **Transport management**: Abstract RabbitMQ, SQS, Kafka differences
- **Observability**: Emit metrics, logs for monitoring
- **Reliability**: Handle retries, timeouts, error routing

## How It Works

1. Consume message from actor's queue (`asya-{actor-name}`)
2. Validate envelope structure
3. Forward to runtime via Unix socket
4. Receive response from runtime
5. Route to next actor or end queue
6. Ack/nack message

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

If sidecar crashes before processing:
- Message nacked, requeued
- After max retries → DLQ (configured by queue)

### Runtime Errors (Ack + Route to error-end)

If runtime returns error:
- Message acked (removed from queue)
- Envelope sent to `error-end` queue
- `error-end` crew actor handles retry logic

### Timeout (Ack + Route to error-end)

If runtime exceeds timeout:
- Sidecar kills connection
- Creates timeout error envelope
- Sends to `error-end` queue
- Message acked

## Routing Logic

### Normal Flow

1. Send envelope to runtime
2. Runtime increments `route.current`
3. Sidecar routes to `route.actors[current]` queue

### End of Route

When `route.current >= len(route.actors)`:
- Route to `happy-end` queue

### Empty Response

When runtime returns `null` or `[]`:
- Route to `happy-end` queue (abort pipeline)

### Error Response

When runtime returns error object:
- Route to `error-end` queue

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_ACTOR_NAME` | (required) | Actor name (for queue name) |
| `ASYA_TRANSPORT` | (required) | Transport type: `sqs`, `rabbitmq` |
| `ASYA_RUNTIME_TIMEOUT` | `5m` | Processing timeout per message |
| `ASYA_SOCKET_DIR` | `/var/run/asya` | Unix socket directory |
| `ASYA_GATEWAY_URL` | - | Gateway URL for status reporting |
| `AWS_REGION` | - | AWS region (for SQS) |
| `RABBITMQ_HOST` | - | RabbitMQ host |

Transport-specific config injected by operator based on `spec.transport`.

## Metrics

Sidecar exposes OpenTelemetry metrics:

- `asya_sidecar_messages_received_total`
- `asya_sidecar_messages_processed_total`
- `asya_sidecar_processing_duration_seconds`
- `asya_sidecar_errors_total{type}`
- `asya_sidecar_timeouts_total`

**See**: [observability.md](observability.md) for complete metrics.
