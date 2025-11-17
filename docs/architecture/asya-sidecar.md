# Sidecar Architecture

Detailed architecture of the Asya🎭 Actor Sidecar.

> **Source**: [`src/asya-sidecar/README.md`](../../src/asya-sidecar/README.md)

## Overview

The Asya🎭 Actor Sidecar is a Go-based message routing service that sits between async message queues and actor runtime processes. It implements a pull-based architecture with pluggable transport layer.

## Key Features

- RabbitMQ support (pluggable transport interface)
- Unix socket communication with runtime
- Fan-out support (array responses)
- End actor mode
- Automatic error routing
- Prometheus metrics exposure

## Quick Start

```bash
export ASYA_ACTOR_NAME=my-queue
export ASYA_RABBITMQ_URL=amqp://guest:guest@localhost:5672/
./bin/sidecar
```

## Design Principles

1. **Transport Agnostic**: Pluggable interface supports multiple queue systems
2. **Simple Protocol**: JSON-based messaging over Unix sockets
3. **Fault Tolerant**: Automatic retry via NACK, timeout handling, graceful degradation
4. **Stateless**: Each message processed independently with no shared state
5. **Observable**: Structured logging for all operations

## Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Asya🎭 Actor Sidecar                       │
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
  - Next actor in route if available
  - Happy-end if route complete or empty response
  - Error-end if error or timeout
- Send message(s) to destination queue(s)

### 4. Acknowledgment Phase
```
Router → Transport.Ack/Nack()
```
- ACK on successful processing
- NACK on error for retry

## Response Handling Summary

| Response | Action |
|----------|--------|
| Single value | Route to next actor |
| Array (fan-out) | Route each to next actor |
| Empty | Send to happy-end |
| Error | Send to error-end |
| Timeout | Send to error-end |
| End of route | Send to happy-end |

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

### Transport failures
Asya🎭 operator owns the queues if deployed with `ASYA_QUEUE_AUTO_CREATE=true`.
This means, it will try to recreate a queue if it doesn't exist or its configuration is not as desired.

Sidecar can detect queue errors and fail after graceful period that will cause pod restart.
Consider scenario:
1. Queue gets deleted (chaos scenario, accidental deletion, infrastructure failure)
2. Sidecar detects missing queue when trying to consume messages
3. Sidecar retries with exponential backoff (`ASYA_QUEUE_RETRY_MAX_ATTEMPTS=10` attempts, `ASYA_QUEUE_RETRY_BACKOFF=1s` seconds initial backoff)
4. Operator health check (every 5 min) detects missing queue and recreates it (if `ASYA_QUEUE_AUTO_CREATE=true`)
5. Sidecar successfully reconnects once queue is recreated (or enters failing state otherwise)


## Runtime Protocol

### Request Format
```
Raw JSON bytes (payload only)
```

### Success Response

Runtime returns the mutated payload directly:

**Single value:**
```json
{"processed": true, "timestamp": "2025-10-24T12:00:00Z"}
```

**Array (fan-out):**
```json
[{"chunk": 1}, {"chunk": 2}]
```

**Empty (no further processing):**
```json
null
```
or
```json
[]
```

### Error Response
```json
{
  "error": "error_code",
  "message": "Error description",
  "type": "ExceptionType"
}
```

## End Actor Mode

For end actors (happy-end, error-end), set `ASYA_IS_END_ACTOR=true` to disable response routing.

```bash
export ASYA_ACTOR_NAME=happy-end
export ASYA_IS_END_ACTOR=true
./bin/sidecar
```

The sidecar will consume messages, forward to runtime, discard responses, and ACK. This is used for end-of-pipeline processing where no further routing is needed.

## Deployment Patterns

### Kubernetes Sidecar (Automatic)

The Asya🎭 operator automatically injects the sidecar when you deploy an AsyncActor CRD.

### Manual Deployment

```yaml
containers:
- name: asya-runtime
  image: my-actor:latest
  volumeMounts:
  - name: socket
    mountPath: /tmp/sockets
- name: sidecar
  image: asya-sidecar:latest
  env:
    - name: ASYA_ACTOR_NAME
      value: "my-actor-queue"
  volumeMounts:
  - name: socket
    mountPath: /tmp/sockets
volumes:
- name: socket
  emptyDir: {}
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

## Configuration

All configuration via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_ACTOR_NAME` | _(required)_ | Queue to consume |
| `ASYA_SOCKET_PATH` | `/tmp/sockets/app.sock` | Unix socket path |
| `ASYA_RUNTIME_TIMEOUT` | `5m` | Response timeout |
| `ASYA_STEP_HAPPY_END` | `happy-end` | Success queue |
| `ASYA_STEP_ERROR_END` | `error-end` | Error queue |
| `ASYA_IS_END_ACTOR` | `false` | End actor mode |
| `ASYA_GATEWAY_URL` | `""` | Gateway URL for progress reporting (optional) |
| `ASYA_RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` | RabbitMQ connection |
| `ASYA_RABBITMQ_EXCHANGE` | `asya` | Exchange name |
| `ASYA_RABBITMQ_PREFETCH` | `1` | Prefetch count |

**Benefits**:
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


## Failure Behavior and Recovery

### Sidecar Container Failure

**What happens:**
- Kubernetes automatically restarts the sidecar container (`restartPolicy: Always`)
- Messages in-flight are NACK'd and redelivered by RabbitMQ
- Runtime container continues running independently

**Message guarantees:**
- ✅ No message loss (NACK before ACK)
- ⚠️ Possible duplicate processing if sidecar dies after routing but before ACK
- ✅ Fast recovery (sub-second container restart)

**Critical window:** Between routing response to the next actor and ACK current message. If sidecar crashes in this window, the next queue receives the message but RabbitMQ redelivers the original.

### Runtime Container Failure

#### Crash/OOM Kill
**Detection:** Sidecar fails to connect to Unix socket (`failed to connect to runtime socket`)

**Recovery:**
1. Sidecar routes message to `error-end` queue with connection error
2. Kubernetes restarts runtime container automatically
3. Socket recreated on shared emptyDir volume
4. Next message attempt succeeds

**Message fate:** Sent to error-end for retry logic (not automatically retried)

#### Timeout (Hung Process)
**Detection:** No response within `ASYA_RUNTIME_TIMEOUT` (default: 5m)

**Recovery:**
1. Socket read returns `context.DeadlineExceeded`
2. Message sent to error-end with timeout error
3. ⚠️ **Container NOT restarted** (no liveness probe configured)
4. Runtime becomes a zombie, failing all subsequent messages

**Operational impact:** Requires manual pod restart or liveness probe configuration.

#### User Code Exception
**Detection:** Runtime returns error response with traceback

**Recovery:**
1. Error routed to error-end with full exception details
2. Runtime container remains healthy (exception was caught)
3. Ready to process next message

**Message fate:** Sent to error-end with detailed error context for debugging

### Message Delivery Guarantees

| Failure Scenario | Message Lost? | Auto Recovery | Notes |
|------------------|---------------|---------------|-------|
| Sidecar crash | ❌ No | ✅ Yes (fast) | NACK → redelivery |
| Runtime crash | ❌ No | ✅ Yes | Via error-end queue |
| Runtime OOM | ❌ No | ✅ Yes (may CrashLoopBackoff) | Via error-end queue |
| Runtime timeout | ❌ No | ⚠️ No (zombie pod) | Via error-end, needs manual restart |
| Pod eviction | ❌ No | ✅ Yes | Full pod restart |
| Socket corruption | ❌ No | ✅ Yes | Transient, usually recovers |

### At-Least-Once Semantics

The sidecar implements **at-least-once delivery**, not exactly-once:
- Messages ACK'd only after successful routing
- Failures before ACK result in redelivery
- Downstream actors **must be idempotent** to handle duplicates

### Operational Considerations

**Recommended for production:**

1. **Add liveness probe** to detect hung runtimes:
   ```yaml
   livenessProbe:
     exec:
       command: ["test", "-S", "/tmp/sockets/app.sock"]
     periodSeconds: 60
     timeoutSeconds: 5
     failureThreshold: 3
   ```

2. **Implement retry logic** in error-end actor (exponential backoff, max attempts)

3. **Monitor timeout metrics** (`asya_actor_runtime_errors_total{error_type="timeout"}`)

4. **Set resource limits** to prevent zombie containers from consuming excessive resources

5. **Configure readiness probes** to prevent routing to unhealthy pods during startup

## Metrics and Observability

The sidecar exposes Prometheus metrics for monitoring. See [Metrics Reference](observability.md) for details.

## Next Steps

- [Envelope Flow](protocol-envelope.md) - Detailed envelope routing
- [Runtime Component](asya-runtime.md) - Actor runtime
- [Metrics Reference](observability.md) - Monitoring
