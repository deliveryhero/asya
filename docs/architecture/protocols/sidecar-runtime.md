# Sidecar-Runtime Protocol

Communication between Asya sidecar (Go) and runtime (Python) uses **HTTP/1.1 over a Unix domain socket**.

## Transport

- **Socket path**: `/var/run/asya/asya-runtime.sock` (default; override with `ASYA_SOCKET_DIR` + `ASYA_SOCKET_NAME` for testing)
- **Protocol**: HTTP/1.1 — standard `net/http` client (Go) and `http.server.HTTPServer` (Python)
- **One connection per message** — no persistent pooling; clean state between requests

## Startup Readiness

The runtime uses **late binding**: the HTTP server starts _after_ `_load_function()` completes. This means:

1. Runtime loads and validates the user handler (may take seconds for model loading)
2. HTTP server binds the Unix socket and starts listening
3. Ready-file `runtime-ready` is written to `SOCKET_DIR`
4. Sidecar polls the ready-file (500 ms interval), then verifies the socket connection

Sidecar never sees a listening socket before the handler is fully loaded — no race condition at startup.

## Endpoints

### `POST /invoke` — Process a message

**Request** (sidecar → runtime):

```http
POST /invoke HTTP/1.1
Content-Type: application/json
Content-Length: <n>

{
  "id": "msg-123",
  "route": {"actors": ["step1", "step2"], "current": 0},
  "payload": {"text": "Hello"},
  "headers": {"trace_id": "abc"}
}
```

**Response codes**:

| HTTP Status | Meaning | Body |
|-------------|---------|------|
| `200 OK` | Handler returned one or more frames | `{"frames": [...]}` |
| `204 No Content` | Handler returned `None` — abort pipeline | empty |
| `400 Bad Request` | Malformed JSON or validation error | `{"error": "msg_parsing_error", "details": {...}}` |
| `500 Internal Server Error` | Unhandled handler exception | `{"error": "processing_error", "details": {...}}` |

**Success response** (`200`):

```json
{
  "frames": [
    {
      "payload": {"text": "Hello", "processed": true},
      "route": {"actors": ["step1", "step2"], "current": 1},
      "headers": {"trace_id": "abc"}
    }
  ]
}
```

Fan-out handlers (generators) produce multiple frames in the same `frames` array.

**Error response** (`400` / `500`):

```json
{
  "error": "processing_error",
  "details": {
    "message": "division by zero",
    "type": "builtins.ZeroDivisionError",
    "mro": ["builtins.ArithmeticError", "builtins.Exception"],
    "traceback": "Traceback (most recent call last):\n  ..."
  }
}
```

### `GET /healthz` — Kubernetes readiness probe

Returns `200 OK` once the HTTP server is listening (i.e., after handler loading completes).

```http
GET /healthz HTTP/1.1

HTTP/1.1 200 OK
Content-Type: application/json

{"status": "ready"}
```

Any unknown path returns `404 Not Found`.

## Error Categories

**Runtime-returned error codes** (in `"error"` field of `400`/`500` responses):

| Code | Cause | Sidecar action |
|------|-------|----------------|
| `msg_parsing_error` | Malformed JSON or missing required fields | Route to `x-sump` |
| `processing_error` | Unhandled Python exception in handler | Route to `x-sump` |

**Sidecar-side errors** (not from runtime):

| Error | Cause | Action |
|-------|-------|--------|
| `context.DeadlineExceeded` | Runtime exceeded `ASYA_RUNTIME_TIMEOUT` | Send to `x-sump`, crash pod |
| HTTP parse error | Unexpected non-HTTP response | Route to `x-sump` |

## Timeout Strategy

Sidecar enforces a per-message timeout (default: 5 minutes) via `context.WithTimeout`:

**On timeout** (`context.DeadlineExceeded`):
1. Sidecar sends the message to `x-sump` with a timeout error
2. Sidecar **crashes the pod** (exits with status code 1)
3. Kubernetes restarts the pod to recover clean state

**Rationale**: prevents zombie processing where the runtime may still be executing after the sidecar gives up.

**Configuration**: `ASYA_RUNTIME_TIMEOUT` (default: `5m`)

## Debugging with curl

Inspect the runtime directly without a sidecar:

```bash
# Invoke handler
curl --unix-socket /var/run/asya/asya-runtime.sock \
  -X POST http://localhost/invoke \
  -H "Content-Type: application/json" \
  -d '{"id":"dbg-1","route":{"actors":["my-actor"],"current":0},"payload":{"x":1}}'
# → 200 {"frames":[{"payload":{"x":1},"route":{"actors":["my-actor"],"current":1}}]}

# Check handler readiness
curl --unix-socket /var/run/asya/asya-runtime.sock http://localhost/healthz
# → 200 {"status":"ready"}
```

## Configuration Reference

### Runtime Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_HANDLER` | (required) | Handler path (`module.function` or `module.Class.method`) |
| `ASYA_HANDLER_MODE` | `payload` | Mode: `payload` or `envelope` |
| `ASYA_SOCKET_CHMOD` | `0o666` | Socket file permissions (octal string) |
| `ASYA_ENABLE_VALIDATION` | `true` | Enable message validation |
| `ASYA_LOG_LEVEL` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### Sidecar Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_RUNTIME_TIMEOUT` | `5m` | Processing timeout per message |
| `ASYA_ACTOR_NAME` | (required) | Actor name for queue consumption |
