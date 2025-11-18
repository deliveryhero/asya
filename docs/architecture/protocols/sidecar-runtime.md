# Sidecar-Runtime Protocol

Communication between Asya sidecar (Go) and runtime (Python) via Unix domain socket.

## Connection Lifecycle

1. Runtime creates Unix socket at `ASYA_SOCKET_PATH` (default: `/var/run/asya/asya-runtime.sock`)
2. Sidecar connects to socket for each message
3. Request-response cycle executes
4. Connection closes
5. Repeat for next message

**One connection per message** - no pooling to ensure clean state.

## Framing Protocol

All messages use **4-byte big-endian length prefix**:

```
+-------------------+---------------------------+
| Length (4 bytes)  | Payload (Length bytes)    |
+-------------------+---------------------------+
| Big-endian uint32 | JSON data                 |
+-------------------+---------------------------+
```

**Python** (sending):
```python
length = struct.pack(">I", len(data))
sock.sendall(length + data)
```

**Go** (receiving):
```go
length := make([]byte, 4)
io.ReadFull(conn, length)
size := binary.BigEndian.Uint32(length)
data := make([]byte, size)
io.ReadFull(conn, data)
```

## Message Format

### Request (Sidecar → Runtime)

Full envelope from queue:
```json
{
  "id": "123",
  "route": {
    "actors": ["step1", "step2"],
    "current": 0
  },
  "payload": {"text": "Hello"},
  "headers": {"trace_id": "abc"}
}
```

### Response (Runtime → Sidecar)

**Success** (single result):
```json
{
  "id": "123",
  "route": {
    "actors": ["step1", "step2"],
    "current": 1
  },
  "payload": {"text": "Hello", "processed": true},
  "headers": {"trace_id": "abc"}
}
```

**Fan-out** (multiple results):
```json
[
  {"chunk": 1, "data": "..."},
  {"chunk": 2, "data": "..."}
]
```

**Empty** (abort):
```json
null
```

**Error**:
```json
{
  "error": "processing_error",
  "message": "Invalid input",
  "type": "ValueError"
}
```

## Error Categories

Runtime returns errors in this format:
```json
{
  "error": "processing_error",
  "details": {
    "message": "Invalid input",
    "type": "ValueError",
    "traceback": "..."
  }
}
```

**Error codes** (returned by runtime):

| Error Code | Cause | Action |
|------------|-------|--------|
| `processing_error` | Handler exception (any unhandled Python exception) | Route to `error-end` |
| `connection_error` | Socket failure or connection handling error | Route to `error-end` |

**Sidecar-side errors** (not from runtime):

| Error | Cause | Action |
|-------|-------|--------|
| Timeout (`context.DeadlineExceeded`) | Runtime execution exceeded timeout | Crash pod to prevent zombie processing |
| Parse error | Malformed JSON from runtime | Route to `error-end` |

## Timeout Strategy

Sidecar enforces overall timeout (default: 5 minutes):
```go
ctx, cancel := context.WithTimeout(ctx, c.timeout)
conn.SetDeadline(deadline)
```

**On timeout** (`context.DeadlineExceeded`):
1. Sidecar sends envelope to `error-end` queue with timeout error
2. Sidecar logs error and **crashes pod** (exits with status code 1)
3. Kubernetes restarts pod to recover clean state

**Rationale**: Prevents zombie processing where runtime may still be working after timeout

**Configuration**: `ASYA_RUNTIME_TIMEOUT` (default: `5m`)

**IMPORTANT**: Timeout crashes the pod for both end actors and regular actors to ensure clean state recovery.


## Configuration Reference

### Runtime Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_SOCKET_PATH` | `/var/run/asya/asya-runtime.sock` | Unix socket path |
| `ASYA_HANDLER` | (required) | Handler path (`module.Class.method`) |
| `ASYA_HANDLER_MODE` | `payload` | Mode: `payload` or `envelope` |

### Sidecar Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_SOCKET_PATH` | `/var/run/asya/asya-runtime.sock` | Unix socket path |
| `ASYA_RUNTIME_TIMEOUT` | `5m` | Processing timeout per message |
| `ASYA_ACTOR_NAME` | (required) | Actor name for queue consumption |

## Best Practices

### For Handler Authors

1. Monitor processing time, return early if approaching timeout limit
2. Use context managers for resource cleanup
3. Return `None` or `[]` to abort pipeline early
4. Avoid global caches that leak memory across requests
5. Use structured logging
6. Handle exceptions gracefully - runtime will catch unhandled exceptions and return `processing_error`

### For Operators

1. Set appropriate timeout balancing task duration and responsiveness
2. Monitor OOM and timeout frequencies
3. Size resources adequately for workload
4. Test failure modes in staging
5. Set container memory limits as defense-in-depth
