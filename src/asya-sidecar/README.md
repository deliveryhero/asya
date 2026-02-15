# Asya🎭 Actor Sidecar (Go)

Go-based sidecar implementing the 🎭 Actor protocol for message routing between queues and runtimes.

## Quick Start

```bash
export ASYA_ACTOR_NAME=my-actor
export ASYA_RABBITMQ_URL=amqp://user:pass@localhost:5672/
./bin/sidecar
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_ACTOR_NAME` | _(required)_ | Actor name (used as queue name) |
| `ASYA_SOCKET_DIR` | `/var/run/asya` | Directory for Unix socket (socket is `asya-runtime.sock`) |
| `ASYA_RUNTIME_TIMEOUT` | `5m` | Runtime response timeout |
| `ASYA_ACTOR_SINK` | `x-sink` | Success end queue |
| `ASYA_ACTOR_SUMP` | `x-sump` | Error end queue |
| `ASYA_IS_END_ACTOR` | `false` | End actor mode (no routing) |
| `ASYA_GATEWAY_URL` | `""` | Gateway URL for progress reporting (optional) |
| `ASYA_RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` | RabbitMQ connection |
| `ASYA_RABBITMQ_EXCHANGE` | `asya` | Exchange name |
| `ASYA_RABBITMQ_PREFETCH` | `1` | Prefetch count |

## Message Format

See [docs/architecture/protocols/actor-actor.md](../../docs/architecture/protocols/actor-actor.md) for complete message structure and routing details

## Building

```bash
cd src/asya-sidecar
go build -o bin/sidecar ./cmd/sidecar
```

## Runtime Protocol

**Request:** Raw payload bytes

**Success response:**

Runtime returns mutated payload directly:
- Single value: `{"processed": true, "data": "..."}`
- Generator (fan-out): Multiple frames yielded over the socket, one per output
- Empty: `null`

**Error response:**
```json
{"error": "code", "message": "..."}
```

## Response Handling

| Response | Action |
|----------|--------|
| Single value | Route to next actor |
| Generator (fan-out) | Route each yielded frame to next actor |
| Empty (`null`) | Send to x-sink |
| Error | Send to x-sump |
| Timeout | Send to x-sump |
| End of route | Send to x-sink |

## Progress Reporting

When `ASYA_GATEWAY_URL` is set, the sidecar automatically reports progress to the gateway:

- **Received**: When message is received from queue
- **Processing**: Before forwarding to runtime
- **Completed**: After successful runtime response

Progress percentage is calculated by the gateway based on `route.current` and `route.actors` length:
```
progress = (current * 100 + statusWeight) / totalSteps
```

**Dynamic Route Modification**: If the runtime adds more actors to the route, the progress percentage may jump down (e.g., 50% → 30%). This is expected behavior.

## End Actor Mode

Set `ASYA_IS_END_ACTOR=true` for end actors (x-sink, x-sump) to disable response routing:

```bash
export ASYA_ACTOR_NAME=x-sink
export ASYA_IS_END_ACTOR=true
./bin/sidecar
```

Sidecar will consume messages, forward to runtime, discard responses, and ACK
