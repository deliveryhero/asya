# Asya Actor Runtime

A lightweight Unix socket server designed to be injected into AI model containers via ConfigMap. It handles communication between the actor sidecar and your Python application.

## Requirements

- **Python**: 3.13+
- **Dependencies**: None (stdlib only)
- **Development**: [uv](https://github.com/astral-sh/uv) for testing and package management

## Overview

The runtime is a single Python file (`asya_runtime.py`) that:
- Listens on a Unix socket for requests from the sidecar
- Uses length-prefix framing (4-byte big-endian uint32) for reliable message framing
- Dynamically loads your function from any Python module
- Handles errors gracefully with proper categorization
- No global state, functional design with closures

## Usage

Set the `ASYA_HANDLER` environment variable to your function:

```bash
# Format: module.path.function_name
export ASYA_HANDLER="my_app.handler.predict"
python asya_runtime.py

# Example with full path
export ASYA_HANDLER="foo.bar.baz.process"
python asya_runtime.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_SOCKET_PATH` | `/tmp/sockets/app.sock` | Path to Unix socket |
| `ASYA_HANDLER` | _(required)_ | Full function path (format: `module.path.function_name`) |
| `ASYA_INCLUDE_METADATA` | `false` | Include route and other metadata in msg dict (`true`/`1`/`yes` to enable) |
| `ASYA_CHUNK_SIZE` | `4096` | Socket receive buffer size in bytes |
| `ASYA_HANDLER_TIMEOUT` | `0` (disabled) | Optional warning timeout in seconds (0 to disable) |
| `ASYA_ENABLE_OOM_DETECTION` | `true` | Enable OOM error detection and categorization |
| `ASYA_CUDA_CLEANUP_ON_OOM` | `true` | Clear CUDA cache on CUDA OOM errors |

## Function Contract

Your function must accept a `msg` dict and return a dict:

```python
def your_function(msg: dict) -> dict:
    """
    Process a message and return a result.

    Args:
        msg: Dict with at minimum {"payload": {...}}
             If ASYA_INCLUDE_METADATA=true, also contains {"route": {...}, "payload": {...}}

    Returns:
        Dict with the processing result (single value or list for fan-out)

    Raises:
        Any exception is caught and returned as processing_error
    """
    payload = msg["payload"]  # Always a dict

    # Your logic here
    result = process(payload)

    return {"result": result}
```

**Key points:**
- `msg["payload"]` is a dict (parsed from JSON)
- Return value can be a single dict or a list of dicts (for fan-out)
- All exceptions are caught and returned as errors

## Response Format

All responses include a `"status"` field for consistent parsing.

### Success
```json
{
  "status": "ok",
  "result": {...}
}
```

### Errors
```json
{
  "status": "error",
  "error": "error_code",
  "message": "error description",
  "type": "ExceptionClass",  // optional, Python exception class name
  "severity": "recoverable|fatal",  // optional, retry hint
  "retry_after": 30  // optional, suggested retry delay in seconds
}
```

**Error codes:**
- `oom_error`: RAM out of memory (`MemoryError`) - **recoverable**, retry after 30s
- `cuda_oom_error`: CUDA GPU memory exhausted - **recoverable**, retry after 60s
- `processing_error`: Exception in user function - **fatal**
- `invalid_json`: Failed to parse JSON or decode UTF-8 - **fatal**
- `connection_error`: Connection handling failed - **fatal**

**Error severity:**
- `recoverable`: Error may succeed on retry (OOM errors after cleanup)
- `fatal`: Permanent error, retry unlikely to help

## Example

```python
# my_app/handler.py
def predict(msg):
    """AI model inference function."""
    payload = msg["payload"]

    if "prompt" not in payload:
        raise ValueError("Missing required field: prompt")

    # Your AI model inference here
    result = my_model.generate(payload["prompt"])

    return {
        "generated_text": result,
        "model": "my-model-v1"
    }
```

```bash
export ASYA_HANDLER="my_app.handler.predict"
python asya_runtime.py
```

### Fan-out Example

```python
def process(msg):
    """Process and fan-out to multiple actors."""
    payload = msg["payload"]

    # Return list for fan-out
    return [
        {"task": "analyze", "data": payload["text"]},
        {"task": "summarize", "data": payload["text"]},
        {"task": "translate", "data": payload["text"]}
    ]
```

## Development

```bash
# Show available commands
make help

# Install dependencies
make deps

# Format code
make fmt

# Run linters
make lint

# Run tests
make test

# Run tests with coverage
make test-cov

# Clean build artifacts
make clean
```

## Testing

```bash
# Using Makefile (recommended)
make test

# Or run directly with uv
uv run pytest tests/ -v

# With coverage report
make test-cov

# All tests should pass with 0 warnings
```

## Protocol

The runtime uses **length-prefix framing** for reliable message transmission:

```
[4 bytes: length (big-endian uint32)][N bytes: JSON payload]
```

- Max message size: 4GB (uint32 max)
- Works with any content type (JSON, binary, media)
- No delimiter collision issues
- Industry standard (HTTP/2, gRPC, Protocol Buffers)

## Resource Management

### OOM Detection

The runtime automatically detects and handles out-of-memory conditions:

**RAM OOM** (`MemoryError`):
- Triggers Python garbage collection
- Returns `oom_error` with `severity: "recoverable"`
- Suggests retry after 30 seconds
- Runtime continues serving after cleanup

**CUDA OOM** (PyTorch/TensorFlow GPU OOM):
- Detects common CUDA OOM patterns
- Clears CUDA cache via `torch.cuda.empty_cache()`
- Returns `cuda_oom_error` with `severity: "recoverable"`
- Suggests retry after 60 seconds

Example OOM response:
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

**Configuration:**
- Set `ASYA_ENABLE_OOM_DETECTION=false` to disable OOM detection
- Set `ASYA_CUDA_CLEANUP_ON_OOM=false` to skip CUDA cache cleanup

### Best Practices

1. **Set container memory limits** as defense-in-depth
2. **Monitor OOM rates** to right-size resources
3. **Batch large inputs** to avoid OOM
4. **Clear caches** after processing large items
5. **Use streaming** for large responses

## Deployment

The runtime is designed to be injected into your container via ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: asya-runtime
data:
  asya_runtime.py: |
    # (full content of asya_runtime.py)
```

Mount it in your pod:

```yaml
volumeMounts:
  - name: runtime
    mountPath: /app/asya_runtime.py
    subPath: asya_runtime.py
volumes:
  - name: runtime
    configMap:
      name: asya-runtime
```

Then in your entrypoint:

```bash
# Set your function
export ASYA_HANDLER="my_app.handler.predict"

# Start runtime in background
python /app/asya_runtime.py &

# Start your main application
python your_app.py
```
