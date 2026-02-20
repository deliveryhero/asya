---
title: Redesign Protocol Sidecar-Runtime
status: open
priority: 2 # medium
type: epic
---

Replace the custom binary framing protocol between sidecar (Go) and runtime (Python) with **HTTP over Unix socket**. This enables streaming responses for generator handlers, standard error semantics, debuggability with curl, and future TCP mode for local testing.

## Motivation

The current protocol (`docs/architecture/protocols/sidecar-runtime.md`) uses a custom binary framing: 4-byte big-endian length prefix + JSON body, one connection per message, single request-response.

This protocol is insufficient for the [handler signatures redesign](.aim/aims/1c84.handler-signatures-wip/README.md) which introduces:

- **Generator handlers** that yield multiple downstream frames per invocation
- **Upstream partial frames** for token-by-token LLM streaming to the gateway
- **Mixed frame types** (downstream, upstream-partial, error) in a single response

Extending the binary protocol to handle multi-frame streaming means inventing custom framing, frame type headers, and done-signaling — which is reinventing HTTP badly.

## Key RFCs

- .aim/aims/1c84.handler-signatures-wip/README.md (handler signatures — the consumer of this protocol)
- .aim/aims/1dmf.ready-stateful-actors/README.md (stateful actors — also uses HTTP over Unix socket between runtime and state proxy sidecars)

## Design

### Why HTTP over Unix socket

| Concern | Current binary protocol | HTTP over Unix socket |
|---|---|---|
| **Request/response** | ✅ One frame each way | ✅ POST → response |
| **Fan-out** (multiple results) | ⚠️ JSON array in single frame | ✅ SSE stream |
| **Upstream partials** (token streaming) | ❌ No support | ✅ SSE events |
| **Multiple yields** (generator) | ❌ Single frame response | ✅ Streaming response |
| **Error semantics** | Custom JSON `{"error": ...}` | ✅ HTTP status codes |
| **Debuggability** | Need custom tools | ✅ `curl --unix-socket` |
| **Frame typing** (partial vs final) | Need to invent framing | ✅ SSE event types |
| **Future TCP mode** | Requires protocol redesign | ✅ Same HTTP, different transport |

**Performance**: For AI workloads, handler execution is seconds (LLM inference). Protocol overhead is microseconds (HTTP parsing) vs nanoseconds (binary framing). Unmeasurable in practice.

**Consistency**: The [stateful actors RFC](.aim/aims/1dmf.ready-stateful-actors/README.md) already uses HTTP over Unix socket between runtime and state proxy sidecars. Using the same protocol for sidecar-runtime communication creates a uniform architecture.

### Connection lifecycle

1. Runtime starts HTTP server on Unix socket at `ASYA_SOCKET_PATH` (default: `/var/run/asya/asya-runtime.sock`)
2. Sidecar connects and sends POST request for each message
3. Runtime processes message, streams response
4. Connection closes
5. Repeat for next message

**One connection per message** — no pooling, clean state between invocations.

### Request format (Sidecar → Runtime)

```
POST /invoke HTTP/1.1
Content-Type: application/json

{
  "id": "msg-uuid-001",
  "parent_id": "msg-uuid-000",
  "route": {
    "prev": ["preprocessor"],
    "curr": "analyzer",
    "next": ["postprocessor"]
  },
  "headers": {
    "trace_id": "trace-abc-123",
    "priority": "high"
  },
  "payload": {
    "text": "Hello, world"
  }
}
```

The sidecar sends the **full message** as JSON. The runtime uses this to:
1. Populate the `/tmp/msg/` virtual filesystem (see [handler signatures RFC](.aim/aims/1c84.handler-signatures-wip/README.md))
2. Extract `payload` and call the handler

### Response format (Runtime → Sidecar)

#### Simple handler (return-based)

For handlers that return a single result:

```
HTTP/1.1 200 OK
Content-Type: application/json

{
  "frames": [
    {
      "type": "downstream",
      "route": {
        "prev": ["preprocessor", "analyzer"],
        "curr": "postprocessor",
        "next": []
      },
      "headers": {"trace_id": "trace-abc-123", "priority": "high"},
      "payload": {"text": "Hello, world", "processed": true}
    }
  ]
}
```

The `route` in the response reflects the shift performed by the runtime (`prev` appended, `curr` advanced, `next` popped).

#### Handler abort (return None)

```
HTTP/1.1 204 No Content
```

No frames emitted. Sidecar acks the message with no downstream routing.

#### Generator handler (streaming)

For handlers that yield multiple frames, the runtime uses **Server-Sent Events (SSE)**:

```
HTTP/1.1 200 OK
Content-Type: text/event-stream

event: upstream
data: {"payload": {"token": "hel"}}

event: upstream
data: {"payload": {"token": "hello"}}

event: downstream
data: {"route": {"prev": ["a", "b"], "curr": "c", "next": ["d"]}, "headers": {"trace_id": "abc"}, "payload": {"response": "hello world"}}

event: done
data: {}
```

**Event types**:

| Event | Meaning | Sidecar action |
|---|---|---|
| `downstream` | Frame for next actor | Route to `route.next[0]` queue |
| `upstream` | Partial frame for caller (gateway SSE) | Forward to gateway progress endpoint |
| `done` | Generator exhausted | Close connection |

Each `downstream` event includes the full routing context (route + headers) as snapshotted at the `yield` point. This allows different frames from the same generator to have different routes (e.g., fan-out with per-frame routing).

Each `upstream` event includes only `payload` — the sidecar forwards it to the gateway's progress endpoint with the original message `id`.

The `done` event signals generator exhaustion. If no `downstream` frames were emitted, the sidecar routes to `x-sink` (same as handler returning `None`).

#### Error response

```
HTTP/1.1 500 Internal Server Error
Content-Type: application/json

{
  "error": "processing_error",
  "details": {
    "message": "Invalid input",
    "type": "ValueError",
    "traceback": "Traceback (most recent call last):\n  ..."
  }
}
```

**HTTP status codes**:

| Status | Meaning | Sidecar action |
|---|---|---|
| `200` | Success (JSON or SSE) | Process frames |
| `204` | Abort (handler returned None) | Ack message, no routing |
| `500` | Handler exception | Route to `x-sump` |
| `503` | Runtime not ready (still loading handler) | Retry after delay |

### Timeout strategy

Sidecar enforces overall timeout (default: 5 minutes, configurable via `ASYA_RUNTIME_TIMEOUT`):

- Sidecar sets HTTP client timeout on the request
- On timeout: sidecar sends message to `x-sump` queue with timeout error, then **crashes pod** (exits with status code 1)
- Kubernetes restarts pod to recover clean state

**Rationale**: Prevents zombie processing where runtime may still be working after timeout.

### SSE mid-stream errors

If the handler raises an exception mid-stream (after some frames have been yielded):

```
event: upstream
data: {"payload": {"token": "hel"}}

event: error
data: {"error": "processing_error", "details": {"message": "LLM connection lost", "type": "ConnectionError"}}
```

**Sidecar behavior on mid-stream error**:
- Upstream partial frames already sent to gateway are NOT recalled
- Downstream frames already emitted are NOT recalled (they are independent messages)
- The error is reported to `x-sump` for the original message
- The `done` event is NOT sent (error terminates the stream)

---

## Debugging

HTTP over Unix socket enables debugging with standard tools:

```bash
# Send a test message
curl --unix-socket /var/run/asya/asya-runtime.sock \
  -X POST http://localhost/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test-001",
    "route": {"prev": [], "curr": "my-actor", "next": ["next-actor"]},
    "headers": {},
    "payload": {"text": "hello"}
  }'

# Stream SSE from a generator handler
curl --unix-socket /var/run/asya/asya-runtime.sock \
  -X POST http://localhost/invoke \
  -H "Content-Type: application/json" \
  -N \
  -d '{"id": "test-002", "route": {"prev": [], "curr": "streamer", "next": []}, "headers": {}, "payload": {"prompt": "hello"}}'
```

---

## Future: HTTP over TCP for testing

Because the protocol is standard HTTP, switching from Unix socket to TCP requires only changing the listener:

```python
# Deployed: Unix socket
server = HTTPServer(UnixSocketAddress("/var/run/asya/asya-runtime.sock"))

# Local testing: TCP
server = HTTPServer(("127.0.0.1", 8080))
```

This enables:
- Local development without Unix sockets (works on macOS/Windows)
- Integration testing against real HTTP endpoints
- Load testing with standard HTTP tools (wrk, hey, vegeta)

The handler code and protocol remain identical — only the transport changes.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ASYA_SOCKET_PATH` | `/var/run/asya/asya-runtime.sock` | Unix socket path for runtime HTTP server |
| `ASYA_RUNTIME_TIMEOUT` | `5m` | Processing timeout per message |
| `ASYA_HANDLER` | (required) | Handler path (`module.Class.method`) |
| `ASYA_ACTOR_NAME` | (required) | Actor name for queue consumption (sidecar) |
| `ASYA_MSG_ROOT` | `/tmp/msg` | Root path for message virtual filesystem (see [handler signatures RFC](.aim/aims/1c84.handler-signatures-wip/README.md)) |

---

## Migration from binary protocol

The migration is contained within two components:

**Runtime side** (`asya_runtime.py`):
- Replace `struct.pack(">I", len(data))` + `sock.sendall()` with `http.server.HTTPServer` on Unix socket
- Single endpoint: `POST /invoke`
- Response: JSON (simple handlers) or SSE stream (generators)
- Python stdlib `http.server` or `aiohttp` for async handlers

**Sidecar side** (Go):
- Replace `binary.BigEndian.Uint32` + `io.ReadFull` with `net/http` client over Unix socket
- Go's `net/http` has native Unix socket support via custom `Dialer`
- Parse SSE stream for generator handlers using standard SSE parsing

**No changes needed**:
- Queue consumption logic (RabbitMQ/SQS)
- Progress reporting to gateway
- Routing logic (route shifting, x-sink/x-sump routing)
- Handler code (handlers are unaware of the protocol)

---

## Implementation plan

### Phase 1: Runtime HTTP server
- Replace socket listener with `http.server` / `aiohttp` in `asya_runtime.py`
- `POST /invoke` endpoint with JSON request/response for return-based handlers
- `204 No Content` for abort
- `500` with error JSON for exceptions

### Phase 2: SSE streaming
- Add SSE response mode for generator handlers
- `event: downstream` / `event: upstream` / `event: done` / `event: error`
- Runtime detects handler type (function vs generator) and selects response format

### Phase 3: Sidecar HTTP client
- Replace binary client in Go sidecar with `net/http` Unix socket client
- SSE stream parser for generator responses
- Upstream partial forwarding to gateway

### Phase 4: Integration testing
- Component tests: runtime HTTP server with curl
- Integration tests: sidecar + runtime over Unix socket HTTP
- Verify streaming, fan-out, error handling, timeout behavior
