# Sidecar-Runtime Protocol

Communication between Asya sidecar (Go) and runtime (Python) via Unix domain socket.

## Connection Lifecycle

1. Runtime creates Unix socket at `ASYA_SOCKET_PATH` (default: `/var/run/asya/asya-runtime.sock`)
2. Sidecar connects to socket for each message
3. Request-response cycle executes
4. Connection closes
5. Repeat for next message

**One connection per message**—no pooling to ensure clean state.

## Framing Protocol

All messages use **4-byte big-endian length prefix**:

```
+------------------+---------------------------+
| Length (4 bytes) | Payload (Length bytes)    |
+------------------+---------------------------+
| Big-endian uint32| JSON data                 |
+------------------+---------------------------+
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

| Error Code | Cause | Severity | Action |
|------------|-------|----------|--------|
| `timeout_error` | Sidecar timeout exceeded | Fatal | Route to `error-end` |
| `oom_error` | Python RAM exhausted | Recoverable | Clear GC, route to `error-end` |
| `cuda_oom_error` | GPU memory exhausted | Recoverable | Clear CUDA cache, route to `error-end` |
| `processing_error` | Handler exception | Fatal | Route to `error-end` |
| `invalid_json` | Malformed JSON | Fatal | Route to `error-end` |
| `connection_error` | Socket failure | Fatal | Route to `error-end` |

## Timeout Strategy

### Primary: Sidecar Enforcement

Sidecar enforces overall timeout (default: 5 minutes):
```go
conn.SetDeadline(time.Now().Add(cfg.Timeout))
```

On timeout:
- Connection forcefully closed
- Error sent to `error-end` queue
- Metrics incremented

**Configuration**: `ASYA_RUNTIME_TIMEOUT` (default: `5m`)

### Optional: Runtime Warning

Runtime can optionally warn handler before timeout:
```python
signal.alarm(ASYA_HANDLER_TIMEOUT)  # Warning timeout
```

**Configuration**: `ASYA_HANDLER_TIMEOUT` (seconds, optional)

**Note**: Signal-based timeout unreliable for C extensions (NumPy, PyTorch)—sidecar timeout is essential.

## Resource Management

### RAM OOM Detection

Runtime catches `MemoryError`:
```python
try:
    result = func(msg)
except MemoryError:
    gc.collect()
    return {
        "error": "oom_error",
        "message": "Out of memory",
        "severity": "recoverable",
        "retry_after": 30
    }
```

### CUDA OOM Detection

Runtime detects CUDA memory errors:
```python
if "CUDA" in type(e).__name__ and "memory" in str(e).lower():
    torch.cuda.empty_cache()
    return {
        "error": "cuda_oom_error",
        "message": str(e),
        "severity": "recoverable",
        "retry_after": 60
    }
```

**Configuration**:
- `ASYA_ENABLE_OOM_DETECTION` (default: `true`)
- `ASYA_CUDA_CLEANUP_ON_OOM` (default: `true`)

## Configuration Reference

### Runtime Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_SOCKET_PATH` | `/var/run/asya/asya-runtime.sock` | Unix socket path |
| `ASYA_HANDLER` | (required) | Handler path (`module.Class.method`) |
| `ASYA_HANDLER_MODE` | `payload` | Mode: `payload` or `envelope` |
| `ASYA_ENABLE_OOM_DETECTION` | `true` | Enable OOM detection |
| `ASYA_CUDA_CLEANUP_ON_OOM` | `true` | Clear CUDA cache on OOM |

### Sidecar Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_SOCKET_PATH` | `/var/run/asya/asya-runtime.sock` | Unix socket path |
| `ASYA_RUNTIME_TIMEOUT` | `5m` | Processing timeout per message |
| `ASYA_ACTOR_NAME` | (required) | Actor name for queue consumption |

## Best Practices

### For Handler Authors

1. Catch `MemoryError` and return partial results if possible
2. Monitor processing time, return early if approaching limit
3. Use context managers for resource cleanup
4. Return `None` to abort pipeline early
5. Avoid global caches that leak memory
6. Use structured logging

### For Operators

1. Set appropriate timeout balancing task duration and responsiveness
2. Monitor OOM and timeout frequencies
3. Size resources adequately for workload
4. Test failure modes in staging
5. Set container memory limits as defense-in-depth
