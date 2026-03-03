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

### `POST /invoke` — Process a envelope

**Request** (sidecar → runtime):

```http
POST /invoke HTTP/1.1
Content-Type: application/json
Content-Length: <n>

{
  "id": "msg-123",
  "route": {
    "prev": [],
    "curr": "step1",
    "next": ["step2"]
  },
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
      "route": {
        "prev": ["step1"],
        "curr": "step2",
        "next": []
      },
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
| `context.DeadlineExceeded` | Runtime exceeded `ASYA_RESILIENCY_ACTOR_TIMEOUT` | Send to `x-sump`, crash pod |
| HTTP parse error | Unexpected non-HTTP response | Route to `x-sump` |

## Timeout Strategy

The sidecar enforces timeouts at two levels:

### SLA Pre-Check (Pipeline-Level Deadline)

Before calling the runtime, the sidecar checks `status.deadline_at` on the incoming envelope. If the current time is past the deadline, the envelope is routed directly to `x-sink` with `phase=failed`, `reason=Timeout` — the runtime is never called.

The gateway stamps `status.deadline_at` based on the tool's `timeout_seconds` configuration. This absolute deadline is never mutated as the envelope travels through actors.

### Effective Timeout (Per-Call)

For envelopes that pass the SLA pre-check, the sidecar computes an effective timeout:

```
effective_timeout = min(ASYA_RESILIENCY_ACTOR_TIMEOUT, remaining_SLA)
```

Where `remaining_SLA = deadline_at - now` (only if `deadline_at` is set).

### Runtime Timeout Behavior

**On runtime timeout** (`context.DeadlineExceeded`):
1. Sidecar sends the envelope to `x-sump` with a timeout error
2. Sidecar **crashes the pod** (exits with status code 1)
3. Kubernetes restarts the pod to recover clean state

**Rationale**: crash-on-timeout prevents zombie processing where the runtime may still be executing after the sidecar gives up.

## Debugging with curl

Inspect the runtime directly without a sidecar:

```bash
# Invoke handler
curl --unix-socket /var/run/asya/asya-runtime.sock \
  -X POST http://localhost/invoke \
  -H "Content-Type: application/json" \
  -d '{"id":"dbg-1","route":{"prev":[],"curr":"my-actor","next":[]},"payload":{"x":1}}'
# → 200 {"frames":[{"payload":{"x":1},"route":{"prev":["my-actor"],"curr":"","next":[]}}]}

# Check handler readiness
curl --unix-socket /var/run/asya/asya-runtime.sock http://localhost/healthz
# → 200 {"status":"ready"}
```

## Configuration Reference

### Runtime Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_HANDLER` | (required) | Handler path (`module.function` or `module.Class.method`) |
| `ASYA_SOCKET_CHMOD` | `0o666` | Socket file permissions (octal string) |
| `ASYA_ENABLE_VALIDATION` | `true` | Enable message validation |
| `ASYA_LOG_LEVEL` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### Sidecar Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_RESILIENCY_ACTOR_TIMEOUT` | `5m` | Per-call actor timeout (from XRD `resiliency.actorTimeout`) |
| `ASYA_ACTOR_NAME` | (required) | Actor name for queue consumption |

## Best Practices

### For Handler Authors

1. **Monitor processing time** — return early if approaching the timeout limit; the sidecar will crash the pod on `DeadlineExceeded`, so a graceful early return is preferable.
2. **Use context managers** for resource cleanup (file handles, HTTP clients, DB connections) so teardown happens even when exceptions occur.
3. **Return `None` to abort** — handlers returning `None` produce a `204` response, which routes the envelope to `x-sink` without an error. Use this for intentional pipeline exits, not errors.
4. **Avoid global mutable state** that leaks across requests; class handlers share the instance, so thread-safety matters for concurrent runtimes.
5. **Let exceptions propagate** — the runtime catches all unhandled exceptions and returns `processing_error` with a full traceback. Wrapping everything in a bare `except` hides bugs.
6. **Use structured logging** — log at `DEBUG` during normal processing so `ASYA_LOG_LEVEL=DEBUG` gives full trace without changing code.

### For Operators

1. **Tune `ASYA_RESILIENCY_ACTOR_TIMEOUT`** to balance task duration against responsiveness; short timeouts cause false crashes on slow model inference.
2. **Monitor `x-sump` queue depth** — a growing sump queue signals systematic handler errors or timeout spikes.
3. **Size container memory** for peak model/data size, not average; OOM kills look like pod crashes and are hard to distinguish from timeout crashes without metrics.
4. **Use `GET /healthz`** as the Kubernetes readiness probe target — it becomes available only after the handler is fully loaded, so the pod never receives traffic while still initialising.
5. **Test failure modes in staging** before production: inject bad payloads, simulate timeouts, and verify envelopes land in `x-sump` rather than disappearing silently.
