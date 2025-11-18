# Asya🎭 Actor Sidecar (Go)

Go-based sidecar implementing the Asya🎭 Actor protocol for message routing between queues and runtimes.

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
| `ASYA_STEP_HAPPY_END` | `happy-end` | Success end queue |
| `ASYA_STEP_ERROR_END` | `error-end` | Error end queue |
| `ASYA_IS_END_ACTOR` | `false` | End actor mode (no routing) |
| `ASYA_GATEWAY_URL` | `""` | Gateway URL for progress reporting (optional) |
| `ASYA_RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` | RabbitMQ connection |
| `ASYA_RABBITMQ_EXCHANGE` | `asya` | Exchange name |
| `ASYA_RABBITMQ_PREFETCH` | `1` | Prefetch count |

## Envelope Format

See [docs/architecture/protocols/actor-actor.md](../../docs/architecture/protocols/actor-actor.md) for complete envelope structure and routing details

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
- Array (fan-out): `[{"item": 1}, {"item": 2}]`
- Empty: `null` or `[]`

**Error response:**
```json
{"error": "code", "message": "..."}
```

## Response Handling

| Response | Action |
|----------|--------|
| Single value | Route to next actor |
| Array (fan-out) | Route each to next actor |
| Empty | Send to happy-end |
| Error | Send to error-end |
| Timeout | Send to error-end |
| End of route | Send to happy-end |

## Progress Reporting

When `ASYA_GATEWAY_URL` is set, the sidecar automatically reports progress to the gateway:

- **Received**: When envelope is received from queue
- **Processing**: Before forwarding to runtime
- **Completed**: After successful runtime response

Progress percentage is calculated by the gateway based on `route.current` and `route.actors` length:
```
progress = (current * 100 + statusWeight) / totalSteps
```

**Dynamic Route Modification**: If the runtime adds more actors to the route, the progress percentage may jump down (e.g., 50% → 30%). This is expected behavior.

## End Actor Mode

Set `ASYA_IS_END_ACTOR=true` for end actors (happy-end, error-end) to disable response routing:

```bash
export ASYA_ACTOR_NAME=happy-end
export ASYA_IS_END_ACTOR=true
./bin/sidecar
```

Sidecar will consume messages, forward to runtime, discard responses, and ACK
