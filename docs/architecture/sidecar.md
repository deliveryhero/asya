# Sidecar Architecture

Detailed architecture of the Asya Actor Sidecar.

> 📄 **Source**: [`src/asya-sidecar/ARCHITECTURE.md`](/src/asya-sidecar/ARCHITECTURE.md)

## Overview

The Asya Actor Sidecar is a Go-based message routing service that sits between async message queues and actor runtime processes. It implements a pull-based architecture with pluggable transport layer.

## Design Principles

1. **Transport Agnostic**: Pluggable interface supports multiple queue systems
2. **Simple Protocol**: JSON-based messaging over Unix sockets
3. **Fault Tolerant**: Automatic retry via NACK, timeout handling, graceful degradation
4. **Stateless**: Each message processed independently with no shared state
5. **Observable**: Structured logging for all operations

## Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Asya Actor Sidecar                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────┐     ┌──────────┐     ┌─────────────────┐   │
│  │ Config   │────▶│ Main     │────▶│ Router          │   │
│  └──────────┘     └──────────┘     └────────┬────────┘   │
│                                              │             │
│                   ┌──────────────────────────┼──────────┐ │
│                   │                          │          │ │
│                   ▼                          ▼          ▼ │
│           ┌──────────────┐         ┌──────────────────┐  │
│           │  Transport   │         │ Runtime Client   │  │
│           │  Interface   │         └──────────────────┘  │
│           └──────┬───────┘                 │             │
│                  │                         │             │
│         ┌────────┴────────┐                │             │
│         │                 │                │             │
│         ▼                 ▼                ▼             │
│  ┌─────────────┐   ┌──────────┐   ┌──────────┐         │
│  │ RabbitMQ    │   │ Runtime  │   │ Metrics  │         │
│  │ Transport   │   │ Client   │   │ Server   │         │
│  └─────────────┘   └──────────┘   └──────────┘         │
│         │                 │                │             │
└─────────┼─────────────────┼────────────────┼─────────────┘
          │                 │                │
          ▼                 ▼                ▼
    ┌──────────┐      ┌─────────────┐    ┌──────────┐
    │ RabbitMQ │      │   Actor     │    │Prometheus│
    │ Queues   │      │  Runtime    │    │          │
    └──────────┘      └─────────────┘    └──────────┘
```

## Message Flow

### 1. Receive Phase
```
Queue → Transport.Receive() → Router.ProcessMessage()
```
- Long polling from queue (configurable wait time)
- Parse JSON message structure
- Validate route information

### 2. Processing Phase
```
Router → Runtime Client → Unix Socket → Actor Runtime
```
- Extract payload from message
- Send payload to runtime via Unix socket
- Wait for response with timeout
- Handle multiple response scenarios:
  - Single response
  - Fan-out (array of responses)
  - Empty response (abort)
  - Error response
  - Timeout (no response)

### 3. Routing Phase
```
Router → Route Management → Transport.Send() → Next Queue
```
- Increment route.current counter
- Determine next destination:
  - Next step in route if available
  - Happy-end if route complete or empty response
  - Error-end if error or timeout
- Send message(s) to destination queue(s)

### 4. Acknowledgment Phase
```
Router → Transport.Ack/Nack()
```
- ACK on successful processing
- NACK on error for retry

## Transport Interface

All transports implement this interface:

```go
type Transport interface {
    Receive(ctx context.Context, queueName string) (QueueMessage, error)
    Send(ctx context.Context, queueName string, body []byte) error
    Ack(ctx context.Context, msg QueueMessage) error
    Nack(ctx context.Context, msg QueueMessage) error
    Close() error
}
```

### RabbitMQ Transport

**Features**:
- Topic exchange routing
- Automatic queue declaration and binding
- Prefetch control for load management
- Durable queues and persistent messages

**Configuration**:
- AMQP connection URL
- Exchange name
- Prefetch count

## Runtime Protocol

### Request Format
```
Raw JSON bytes (payload only)
```

### Success Response
```json
{
  "status": "ok",
  "result": <single response or array>
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

## Error Handling Strategy

| Error Type | Action | Destination |
|------------|--------|-------------|
| Parse error | Log + send error | error-end |
| Runtime error | Log + send error | error-end |
| Timeout | Log + construct error | error-end |
| Empty response | Log + send original | happy-end |
| Transport error | Log + NACK | retry queue |
| Shutdown signal | Graceful NACK | retry queue |

## Configuration Strategy

All configuration via environment variables:
- No config files to manage
- Container-friendly
- Easy per-environment customization
- Validation on startup

## Concurrency Model

**Current**: Single-threaded sequential processing
- One message at a time
- Simple error handling
- Predictable behavior

**Future**: Configurable worker pool
- Concurrent message processing
- Higher throughput
- More complex error scenarios

## Deployment Patterns

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

## Metrics and Observability

The sidecar exposes Prometheus metrics for monitoring. See [Metrics Reference](../reference/metrics.md) for details.

## Next Steps

- [Message Flow](messages.md) - Detailed message routing
- [Runtime Component](../components/runtime.md) - Actor runtime
- [Metrics Reference](../reference/metrics.md) - Monitoring
