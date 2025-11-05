# Asya Sidecar

Go-based sidecar for message routing between queues and actor runtimes.

> 📄 **Source Code**: [`src/asya-sidecar/`](/src/asya-sidecar/)
> 📖 **Developer README**: [`src/asya-sidecar/README.md`](/src/asya-sidecar/README.md)
> 🏗️ **Architecture**: [`src/asya-sidecar/ARCHITECTURE.md`](/src/asya-sidecar/ARCHITECTURE.md)
> 📊 **Metrics**: [`src/asya-sidecar/METRICS.md`](/src/asya-sidecar/METRICS.md)

## Overview

The sidecar implements the Asya Actor protocol, handling message routing between async queues and actor runtimes via Unix sockets.

## Responsibilities

1. **Receive** messages from async message queues (RabbitMQ)
2. **Extract** payload and route information
3. **Send** payload to actor runtime via Unix socket
4. **Handle** runtime responses (single, fan-out, or empty)
5. **Route** responses to next destination based on route table
6. **Error handling** with configurable terminal queues

## Message Flow

```
Queue → Sidecar → Unix Socket → Actor Runtime
                ↓
         Route Management
                ↓
         Next Queue / Terminal
```

### Processing Steps

1. **Receive Phase**: Long polling from queue, parse message
2. **Processing Phase**: Send payload to runtime, wait for response
3. **Routing Phase**: Increment route, determine next destination
4. **Acknowledgment Phase**: ACK on success, NACK on error

## Message Format

```json
{
  "route": {
    "steps": ["step1", "step2", "step3"],
    "current": 0
  },
  "payload": <raw bytes>
}
```

## Transport Support

### RabbitMQ (Primary)
- Topic exchange routing
- Queue auto-declaration
- Prefetch configuration
- Automatic message acknowledgment

AWS SQS support has been removed in the current version.

## Configuration

All configuration via environment variables:

### General
- `ASYA_QUEUE_NAME`: Queue to listen on (required)
- `ASYA_SOCKET_PATH`: Unix socket path (default: `/tmp/sockets/app.sock`)
- `ASYA_RUNTIME_TIMEOUT`: Timeout for runtime (default: `5m`)
- `ASYA_STEP_HAPPY_END`: Success queue (default: `happy-end`)
- `ASYA_STEP_ERROR_END`: Error queue (default: `error-end`)

### RabbitMQ
- `ASYA_RABBITMQ_URL`: Connection URL (default: `amqp://guest:guest@localhost:5672/`)
- `ASYA_RABBITMQ_EXCHANGE`: Exchange name (default: `asya`)
- `ASYA_RABBITMQ_PREFETCH`: Prefetch count (default: `1`)

## Runtime Protocol

Communication via Unix socket using JSON:

### Request to Runtime
```
<payload bytes>
```

### Success Response
```json
{
  "status": "ok",
  "result": <single response or array of responses>
}
```

### Error Response
```json
{
  "error": "error_code",
  "message": "Error description",
  "type": "ExceptionType"
}
```

## Response Handling

| Response Type | Action |
|--------------|--------|
| Single response | Route to next step |
| Array (fan-out) | Route each to next step |
| Empty response | Send to happy-end |
| Error | Send to error-end |
| Timeout | Construct error, send to error-end |

## Error Handling

| Error Type | Action | Destination |
|------------|--------|-------------|
| Parse error | Log + send error | error-end |
| Runtime error | Log + send error | error-end |
| Timeout | Log + construct error | error-end |
| Empty response | Log + send original | happy-end |
| Transport error | Log + NACK | retry queue |

## Building

```bash
cd src/asya-sidecar
go mod download
go build -o bin/sidecar ./cmd/sidecar
```

Or use the automated build script:

```bash
# From repository root
./scripts/build-images.sh
```

## Running

```bash
export ASYA_QUEUE_NAME=my-actor-queue
export ASYA_RABBITMQ_URL=amqp://user:pass@localhost:5672/
./bin/sidecar
```

## Deployment Pattern

### Kubernetes Sidecar
```yaml
containers:
- name: runtime
  image: my-actor:latest
  volumeMounts:
  - name: socket
    mountPath: /tmp/sockets
- name: sidecar
  image: asya-sidecar:latest
  env:
    - name: ASYA_QUEUE_NAME
      value: "my-actor-queue"
  volumeMounts:
  - name: socket
    mountPath: /tmp/sockets
volumes:
- name: socket
  emptyDir: {}
```

The Asya operator automatically injects the sidecar container when you create an `Asya` resource.

## Monitoring

The sidecar exposes Prometheus metrics for monitoring. See [Metrics Reference](../reference/metrics.md) for details.

## Architecture Details

For in-depth architecture information, see:
- [`src/asya-sidecar/ARCHITECTURE.md`](/src/asya-sidecar/ARCHITECTURE.md) - Detailed component architecture
- [Architecture Overview](../architecture/overview.md) - System-wide architecture

## Next Steps

- [Runtime Component](runtime.md) - Actor runtime
- [Operator Component](operator.md) - CRD and operator
- [Metrics Reference](../reference/metrics.md) - Monitoring
