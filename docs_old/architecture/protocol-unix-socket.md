# Sidecar-Runtime Protocol Specification

## Overview

This document specifies the communication protocol between the Asya🎭 Sidecar (Go) and Actor Runtime (Python) via Unix domain sockets. The protocol is designed to be robust, handling timeouts, resource exhaustion (RAM/CUDA OOM), and various error conditions gracefully.

## Design Principles

1. **Reliability**: Timeout enforcement at sidecar level prevents runtime hangs
2. **Robustness**: Comprehensive error categorization and handling
3. **Observability**: Detailed error metadata for debugging and monitoring
4. **Resource Safety**: Proper OOM detection and recovery mechanisms
5. **Simplicity**: Length-prefix framing with JSON payloads

## Connection Lifecycle

### 1. Socket Setup

**Runtime Side (Python)**:
```python
# Creates Unix socket at ASYA_SOCKET_PATH
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.bind(socket_path)
sock.listen(5)
os.chmod(socket_path, 0o666)  # Allow sidecar to connect
```

**Sidecar Side (Go)**:
```go
// Connects to Unix socket with timeout
ctx, cancel := context.WithTimeout(ctx, timeout)
conn, err := dialer.DialContext(ctx, "unix", socketPath)
conn.SetDeadline(deadline)  // Enforce overall timeout
```

### 2. Request-Response Cycle

1. Sidecar connects to socket
2. Sidecar sends request with length-prefix
3. Runtime reads request, processes via handler
4. Runtime sends response with length-prefix
5. Connection closes
6. Repeat for next message

**One connection per message** - No connection pooling/reuse to ensure clean state.

### 3. Framing Protocol

All messages use **4-byte big-endian length prefix**:

```
+----------------+---------------------------+
| Length (4 bytes)  | Payload (Length bytes) |
+----------------+---------------------------+
| Big-endian uint32 | JSON data              |
+----------------+---------------------------+
```

**Python** (in `src/asya-runtime/asya_runtime.py`):
```python
def send_msg(sock, data: bytes):
    length = struct.pack(">I", len(data))
    sock.sendall(length + data)

def recv_exact(sock, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(min(remaining, CHUNK_SIZE))
        if not chunk:
            raise ConnectionError("Connection closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
```

**Go** (`src/asya-sidecar/internal/runtime/client.go`):
```go
func SendSocketData(conn net.Conn, data []byte) error {
    length := make([]byte, 4)
    binary.BigEndian.PutUint32(length, uint32(len(data)))
    conn.Write(length)
    conn.Write(data)
    return nil
}

func RecvSocketData(conn net.Conn) ([]byte, error) {
    length := make([]byte, 4)
    io.ReadFull(conn, length)
    size := binary.BigEndian.Uint32(length)
    data := make([]byte, size)
    io.ReadFull(conn, data)
    return data, nil
}
```

## Message Format

### Request (Sidecar → Runtime)

The raw message from the queue:

```json
{
  "id": "123",
  "route": {
    "actors": ["step1", "step2", "step3"],
    "current": 0
  },
  "payload": <arbitrary JSON>,
  "headers": {...}  //optional
}
```

### Response (Runtime → Sidecar)

- list of envelopes: success, send payload(s) further
- empty list or `None`: success, abort execution (send to `happy-end`, ack)
- list with dicts `{"error": <code>, "details": ...}`: error (send to `error-end`, ack)


#### Success Response

**Single Result**:


**Fan-out (Multiple Results)**:
```json
[
  {"chunk": 1, "data": "..."},
  {"chunk": 2, "data": "..."},
  {"chunk": 3, "data": "..."}
]
```

**Empty Result (Abort Execution)**:
```json
null
```
or
```json
[]
```
Routes to `happy-end` queue.

#### Error Response

```json
{
  "status": "error",
  "error": "<error_code>",
  "message": "<human-readable description>",
  "type": "<ExceptionClassName>",
  "severity": "<recoverable|fatal>",
  "retry_after": <seconds>
}
```

**Fields**:
- `status`: Always `"error"` for errors
- `error`: Error code (see Error Categories)
- `message`: Detailed error description
- `type`: Python exception class name (e.g., "ValueError", "MemoryError")
- `severity`: (Optional) `"recoverable"` or `"fatal"` - hints if retry might succeed
- `retry_after`: (Optional) Suggested seconds to wait before retry (for OOM, resource exhaustion)

## Error Categories

### 1. `timeout_error`
**Cause**: Sidecar timeout exceeded
**Severity**: Fatal
**Triggered by**: Sidecar when `ASYA_RUNTIME_TIMEOUT` exceeded
**Action**: Sent to `error-end` queue

**Example**:
```json
{
  "status": "error",
  "error": "timeout_error",
  "message": "Runtime timeout exceeded (5m0s)",
  "severity": "fatal"
}
```

### 2. `oom_error`
**Cause**: Python RAM out of memory
**Severity**: Recoverable
**Triggered by**: `MemoryError` exception in handler
**Action**: Clear Python GC, suggest retry

**Example**:
```json
{
  "status": "error",
  "error": "oom_error",
  "message": "Out of memory during processing",
  "type": "MemoryError",
  "severity": "recoverable",
  "retry_after": 30
}
```

### 3. `cuda_oom_error`
**Cause**: CUDA GPU memory exhausted
**Severity**: Recoverable
**Triggered by**: `torch.cuda.OutOfMemoryError` or similar
**Action**: Clear CUDA cache, suggest retry

**Example**:
```json
{
  "status": "error",
  "error": "cuda_oom_error",
  "message": "CUDA out of memory: Tried to allocate 2.0 GiB",
  "type": "OutOfMemoryError",
  "severity": "recoverable",
  "retry_after": 60
}
```

### 4. `processing_error`
**Cause**: General exception during handler execution
**Severity**: Usually fatal (depends on exception)
**Triggered by**: Any unhandled exception in user handler
**Action**: Sent to `error-end` queue

**Example**:
```json
{
  "status": "error",
  "error": "processing_error",
  "message": "division by zero",
  "type": "ZeroDivisionError",
  "severity": "fatal"
}
```

### 5. `invalid_json`
**Cause**: Malformed JSON in request
**Severity**: Fatal
**Triggered by**: JSON parse error
**Action**: Sent to `error-end` queue

**Example**:
```json
{
  "status": "error",
  "error": "invalid_json",
  "message": "Expecting ',' delimiter: line 1 column 15 (char 14)",
  "type": "JSONDecodeError",
  "severity": "fatal"
}
```

### 6. `connection_error`
**Cause**: Socket/network issues
**Severity**: Fatal
**Triggered by**: Connection drops, socket errors
**Action**: Sent to `error-end` queue

**Example**:
```json
{
  "status": "error",
  "error": "connection_error",
  "message": "Connection closed while reading",
  "type": "ConnectionError",
  "severity": "fatal"
}
```

## Timeout Strategy

### Primary Enforcement: Sidecar (Go)

**Rationale**:
- Go's context and deadline mechanisms are reliable
- Protects against runtime hangs, deadlocks, infinite loops
- Can forcefully terminate connection

**Implementation**:
```go
ctx, cancel := context.WithTimeout(ctx, cfg.Timeout)  // Default: 5 minutes
defer cancel()

conn.SetDeadline(deadline)  // Apply to all socket operations
```

**Configuration**:
- `ASYA_RUNTIME_TIMEOUT`: Overall timeout duration (default: `5m`)
- Applied to entire request-response cycle
- On timeout, connection is closed and error sent to error-end queue

### Secondary (Optional): Runtime (Python)

**Rationale**:
- Allows handler graceful cleanup
- Can warn handler before hard timeout
- Not enforced (sidecar will kill if exceeded)

**Implementation** (Optional):
```python
import signal

def timeout_handler(signum, frame):
    # Warn handler approaching timeout
    # Handler can clean up resources
    pass

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(ASYA_HANDLER_TIMEOUT)  # Warning timeout
```

**Configuration**:
- `ASYA_HANDLER_TIMEOUT`: Optional warning timeout (seconds)
- Should be < sidecar timeout to allow cleanup
- Default: Not set (no warning)

**Note**: Signal-based timeout in Python is **unreliable** for C extension code (numpy, PyTorch), so sidecar timeout is essential.

## Resource Management

### OOM Detection and Recovery

#### RAM OOM (Python)

**Detection**:
```python
try:
    result = func(msg)
except MemoryError as e:
    # Trigger cleanup
    import gc
    gc.collect()
    return {
        "status": "error",
        "error": "oom_error",
        "message": str(e),
        "type": "MemoryError",
        "severity": "recoverable",
        "retry_after": 30
    }
```

**Recovery**:
1. Python GC triggered automatically
2. Runtime continues serving
3. Sidecar may implement retry logic
4. Error routed to error-end for monitoring

#### CUDA OOM

**Detection**:
```python
try:
    result = func(msg)
except Exception as e:
    if "CUDA" in type(e).__name__ and "memory" in str(e).lower():
        # CUDA OOM detected
        if ASYA_CUDA_CLEANUP_ON_OOM:
            try:
                import torch
                torch.cuda.empty_cache()
            except:
                pass
        return {
            "status": "error",
            "error": "cuda_oom_error",
            "message": str(e),
            "type": type(e).__name__,
            "severity": "recoverable",
            "retry_after": 60
        }
```

**Recovery**:
1. CUDA cache cleared via `torch.cuda.empty_cache()`
2. Runtime continues serving
3. Next request may succeed with freed memory

**Configuration**:
- `ASYA_ENABLE_OOM_DETECTION`: Enable OOM detection (default: `true`)
- `ASYA_CUDA_CLEANUP_ON_OOM`: Clear CUDA cache on OOM (default: `true`)

### Resource Limits

**Memory Monitoring** (Future):
- Track memory usage during processing
- Emit warnings at 80% threshold
- Reject requests at 95% threshold

**Connection Limits**:
- One connection per message (no pooling)
- Ensures clean state between requests
- Prevents connection leak accumulation

## Error Handling Flow

```
┌─────────────┐
│   Sidecar   │
└──────┬──────┘
       │ 1. Send request
       ├────────────────────────►┌──────────────┐
       │                         │   Runtime    │
       │                         │              │
       │                         │  2. Process  │
       │                         │     with     │
       │                         │   handler    │
       │                         └──────┬───────┘
       │                                │
       │           ┌────────────────────┴─────────────────┐
       │           │                                      │
       │      Success?                                Error?
       │           │                                      │
       │           ▼                                      ▼
       │   ┌──────────────┐                     ┌──────────────┐
       │   │ Return result│                     │Categorize err│
       │   │ status: ok   │                     │  error code  │
       │   └──────┬───────┘                     │  + severity  │
       │          │                              └──────┬───────┘
       │◄─────────┴──────────────────────────────────┘
       │ 3. Receive response
       │
       ├─────Is Error?────────►Yes───┐
       │                              │
       No                             ▼
       │                    ┌──────────────────┐
       │                    │  Send to         │
       │                    │  error-end queue │
       │                    │  + metrics       │
       │                    └──────────────────┘
       │
       ├─────Empty Result?───►Yes──┐
       │                            │
       No                           ▼
       │                   ┌──────────────────┐
       │                   │  Send to         │
       │                   │  happy-end queue │
       │                   └──────────────────┘
       │
       ▼
┌──────────────┐
│ Route to next│
│ actor or     │
│ happy-end    │
└──────────────┘
```

## Configuration Reference

### Runtime Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_SOCKET_PATH` | `/tmp/sockets/app.sock` | Unix socket path |
| `ASYA_HANDLER` | (required) | Function path (e.g., `module.function`) |
| `ASYA_HANDLER_MODE` | `payload` | Handler mode: `payload` or `envelope` |
| `ASYA_CHUNK_SIZE` | `4096` | Socket read chunk size (bytes) |
| `ASYA_HANDLER_TIMEOUT` | (none) | Optional warning timeout (seconds) |
| `ASYA_ENABLE_OOM_DETECTION` | `true` | Enable OOM detection |
| `ASYA_CUDA_CLEANUP_ON_OOM` | `true` | Clear CUDA cache on CUDA OOM |

### Sidecar Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_SOCKET_PATH` | `/tmp/sockets/app.sock` | Unix socket path |
| `ASYA_RUNTIME_TIMEOUT` | `5m` | Maximum processing time per message |
| `ASYA_ACTOR_NAME` | (required) | RabbitMQ queue to consume from |
| `ASYA_STEP_HAPPY_END` | `happy-end` | Success end queue |
| `ASYA_STEP_ERROR_END` | `error-end` | Error end queue |

## Best Practices

### For Handler Authors

1. **Handle OOM Gracefully**: Catch `MemoryError` and return partial results if possible
2. **Respect Timeout**: Monitor processing time, return early if approaching limit
3. **Clean Up Resources**: Use context managers, close files/connections
4. **Return Early**: Use empty result (`return None`) to abort pipeline early
5. **Avoid Memory Leaks**: Clear large objects, avoid global caches
6. **Log Appropriately**: Use structured logging for debugging

### For Operators

1. **Set Appropriate Timeouts**: Balance between long-running tasks and responsiveness
2. **Monitor Error Rates**: Track OOM, timeout frequencies
3. **Size Resources**: Ensure adequate RAM/CUDA memory for workload
4. **Enable Metrics**: Use Prometheus metrics for observability
5. **Test Failure Modes**: Simulate OOM, timeouts in staging
6. **Set Resource Limits**: Use container memory limits as defense-in-depth

## Testing Strategy

### Unit Tests

**Runtime (Python)**:
- OOM error response format
- CUDA OOM detection (mocked)
- Error severity assignment
- Timeout warning signals
- Resource cleanup after errors

**Sidecar (Go)**:
- Parse error severity/retry_after
- Timeout enforcement
- Error routing by severity
- Connection handling edge cases

### Integration Tests

1. **OOM Recovery**: Trigger RAM OOM, verify error routing and recovery
2. **CUDA OOM**: Trigger CUDA OOM, verify cache clearing
3. **Timeout**: Long-running handler, verify sidecar timeout
4. **Connection Stability**: Runtime crashes, verify graceful degradation
5. **End-to-End**: Full message pipeline with various error scenarios

## Protocol Versioning

**Current Version**: 1.0

**Future Compatibility**:
- New optional fields can be added to responses
- Error codes will not be removed (may be deprecated)
- Length-prefix framing will remain unchanged
- Breaking changes will increment major version

## Metrics and Observability

**Recommended Metrics**:
- `asya_runtime_requests_total{error_code, severity}` - Request count by error type
- `asya_runtime_oom_total{type}` - OOM events (ram, cuda)
- `asya_runtime_timeouts_total` - Timeout events
- `asya_runtime_processing_duration_seconds` - Processing time histogram
- `asya_runtime_memory_bytes` - Current memory usage (if available)

See [Metrics Reference](observability.md) for complete metrics specification.

## Troubleshooting

### Runtime Not Responding

**Symptoms**: Sidecar timeout errors, no responses
**Causes**:
- Runtime crashed/deadlocked
- Handler infinite loop
- Blocking I/O operation

**Solutions**:
- Check runtime logs for crashes
- Add timeout warning to handler
- Use profiling to find blocking code

### Frequent OOM Errors

**Symptoms**: High rate of `oom_error` or `cuda_oom_error`
**Causes**:
- Input data too large
- Memory leak in handler
- Insufficient resources

**Solutions**:
- Increase container memory limits
- Batch process large inputs
- Profile memory usage
- Add input size validation

### Connection Errors

**Symptoms**: `connection_error`, socket failures
**Causes**:
- Socket permission issues
- File descriptor limits
- Network configuration

**Solutions**:
- Check socket path permissions (0o666)
- Increase `ulimit -n`
- Verify socket path matches

## References

- [Actor Runtime Component](asya-runtime.md) - Runtime architecture
- [Sidecar Component](asya-sidecar.md) - Sidecar architecture
- [Metrics Reference](observability.md) - Prometheus metrics
