# Asya Actor Sidecar (Go)

Go-based sidecar process that implements the Asya Actor protocol, providing message routing between async queues and actor runtimes via Unix sockets.

## Overview

The actor sidecar is responsible for:
1. Receiving messages from async message queues (RabbitMQ)
2. Extracting payload and route information
3. Sending payload to actor runtime via Unix socket
4. Handling runtime responses (single, fan-out, or empty)
5. Routing responses to next destination based on route table
6. Error handling with configurable terminal queues

## Architecture

```
Queue → Sidecar → Unix Socket → Actor Runtime
                ↓
         Route Management
                ↓
         Next Queue / Terminal
```

## Message Format

Messages follow this structure:
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

### RabbitMQ
- Topic exchange routing
- Queue auto-declaration
- Prefetch configuration
- Automatic message acknowledgment

## Configuration

All configuration via environment variables:

### General
- `ASYA_QUEUE_NAME`: Name of the queue to listen on (required)
- `ASYA_SOCKET_PATH`: Unix socket path for runtime communication (default: `/tmp/sockets/app.sock`)
- `ASYA_RUNTIME_TIMEOUT`: Timeout for runtime communication (default: `5m`)
- `ASYA_STEP_HAPPY_END`: Terminal queue for successful completions (default: `happy-end`)
- `ASYA_STEP_ERROR_END`: Terminal queue for errors (default: `error-end`)
- `ASYA_IS_TERMINAL`: Terminal actor mode - disables response routing (default: `false`)

### RabbitMQ Configuration
- `ASYA_RABBITMQ_URL`: RabbitMQ connection URL (default: `amqp://guest:guest@localhost:5672/`)
- `ASYA_RABBITMQ_EXCHANGE`: Exchange name (default: `asya`)
- `ASYA_RABBITMQ_PREFETCH`: Prefetch count (default: `1`)

## Building

```bash
cd src/asya-sidecar
go mod download
go build -o bin/sidecar ./cmd/sidecar
```

## Running

```bash
export ASYA_QUEUE_NAME=my-actor-queue
export ASYA_RABBITMQ_URL=amqp://user:pass@localhost:5672/
./bin/sidecar
```

## Runtime Protocol

The sidecar communicates with the actor runtime via Unix socket using JSON:

**Request to runtime:**
```json
<payload bytes>
```

**Response from runtime (success):**
```json
{
  "status": "ok",
  "result": <single response or array of responses>
}
```

**Response from runtime (error):**
```json
{
  "error": "error_code",
  "message": "Error description",
  "type": "ExceptionType"
}
```

## Message Flow

1. **Normal flow**: Payload processed → increment route → send to next step
2. **Fan-out**: Multiple responses → each routed with incremented route
3. **Empty response**: No responses → send original message to happy-end
4. **Timeout**: No response within timeout → construct error → send to error-end
5. **Runtime error**: Error response → send error message to error-end
6. **End of route**: No more steps → send to happy-end
7. **Terminal mode** (`ASYA_IS_TERMINAL=true`): Runtime response discarded, no routing (used for happy-end/error-end actors)

## Terminal Actor Mode

Terminal actors (like `happy-end` and `error-end`) consume messages but do not produce new messages for routing. To prevent infinite routing loops, set `ASYA_IS_TERMINAL=true` for these actors.

**Behavior when `ASYA_IS_TERMINAL=true`:**
- Sidecar receives message from queue
- Sidecar sends message to runtime via Unix socket
- Runtime processes message (e.g., persists results, reports to gateway)
- Runtime returns response (can be any value - will be discarded)
- **Sidecar discards the response and does NOT route it**
- Message is ACKed and processing completes

**Example configuration for happy-end actor:**
```bash
export ASYA_QUEUE_NAME=happy-end
export ASYA_IS_TERMINAL=true
export ASYA_SOCKET_PATH=/tmp/sockets/happy-end.sock
./bin/sidecar
```

**Without `ASYA_IS_TERMINAL`:** The sidecar would try to route the runtime's response, potentially creating an infinite loop if the response is sent back to the same queue.

**With `ASYA_IS_TERMINAL`:** The sidecar consumes the message, calls the runtime, and stops - no routing occurs.

## Error Handling

- **Parsing errors**: Send to error-end with original message
- **Runtime errors**: Send to error-end with error details
- **Timeout**: Send to error-end with timeout message
- **Transport errors**: NACK message for retry
