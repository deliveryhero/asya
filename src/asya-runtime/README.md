# Asya🎭 Actor Runtime

Lightweight Unix socket server for actor-sidecar communication. Single Python file, no dependencies.

**Python Version Support**: 3.7+ (compatible with older AI model frameworks)

## Quick Start

```bash
export ASYA_HANDLER="my_app.handler.predict"
python asya_runtime.py
```

## Deployment Requirements

When deploying actors on Kubernetes, the operator automatically injects the runtime:

1. **Command injection**: The operator sets `command: ["python3", "/opt/asya/asya_runtime.py"]` for all runtime containers
2. **Python availability**: Your container image must have `python3` (version 3.7+) available in PATH
3. **Handler importability**: Your function must be importable by the runtime

**Note**: Python 3.7+ support ensures compatibility with older AI model frameworks and legacy inference servers.

### Custom Python Executable

If your image uses a different Python location, configure it in the Helm chart:

```yaml
workload:
  pythonExecutable: "/opt/conda/bin/python"  # Default: "python3"
  template:
    spec:
      containers:
      - name: asya-runtime
        image: continuumio/miniconda3
```

### Making Your Handler Importable

The runtime uses Python's import system to load your handler. Ensure your module is in `PYTHONPATH`:

**Example 1: Handler in a package**
```yaml
# File structure:
# /app/my_package/handler.py
env:
- name: PYTHONPATH
  value: "/app"
- name: ASYA_HANDLER
  value: "my_package.handler.process"
```

**Example 2: Standalone script**
```yaml
# File structure:
# /foo/bar/script.py with function 'predict'
env:
- name: PYTHONPATH
  value: "/foo/bar"
- name: ASYA_HANDLER
  value: "script.predict"  # No .py extension
```

**Example 3: Multiple paths**
```yaml
env:
- name: PYTHONPATH
  value: "/app:/opt/models"
- name: ASYA_HANDLER
  value: "my_module.inference.run"
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_SOCKET_DIR` | `/var/run/asya` | Directory for Unix socket (socket is `asya-runtime.sock`) |
| `ASYA_HANDLER` | _(required)_ | Full function path (format: `module.path.function_name`) |
| `ASYA_HANDLER_MODE` | `payload` | Handler mode: `payload` (simple) or `envelope` (full access) |
| `ASYA_INCLUDE_METADATA` | `false` | Include route and other metadata in msg dict (`true`/`1`/`yes` to enable) |
| `ASYA_CHUNK_SIZE` | `4096` | Socket receive buffer size in bytes |
| `ASYA_ENABLE_VALIDATION` | `true` | Enable envelope validation (disable for performance) |

Note: Socket path is hardcoded to `{ASYA_SOCKET_DIR}/asya-runtime.sock`

## Handler Modes

### Payload Mode (Default)

Simple mode where handlers work only with payloads. Routes and headers are preserved automatically.

```python
def your_function(payload: dict) -> dict:
    """Process payload and return result."""
    result = process(payload)
    return {"result": result}  # Single value or list for fan-out
```

### Envelope Mode (Advanced)

Full access to envelope structure (payload, route, headers). Required for dynamic routing.

```python
# Set ASYA_HANDLER_MODE=envelope
def your_function(envelope: dict) -> dict:
    """Process full envelope with access to route."""
    payload = envelope["payload"]
    route = envelope["route"]  # {"actors": [...], "current": 0}
    headers = envelope.get("headers", {})

    # Process and return envelope
    return {
        "payload": {"result": process(payload)},
        "route": route,  # Can modify route
        "headers": headers
    }
```

## Route Modification Rules

**IMPORTANT:** When using envelope mode, handlers can modify routes but must follow strict rules:

### ✅ Allowed Operations

1. **Add future steps** (after current position)
   ```python
   # Input:  {"actors": ["a", "b", "c"], "current": 1}
   # Output: {"actors": ["a", "b", "c", "d", "e"], "current": 1}  # Added d, e
   ```

2. **Replace future steps** (after current position)
   ```python
   # Input:  {"actors": ["a", "b", "c"], "current": 0}
   # Output: {"actors": ["a", "x", "y"], "current": 0}  # Replaced b, c with x, y
   ```

3. **Keep current position unchanged**
   ```python
   # Input:  {"actors": ["a", "b"], "current": 0}
   # Output: {"actors": ["a", "b"], "current": 0}  # Same
   ```

### ❌ Forbidden Operations

1. **Erase already-processed steps** (positions 0 to current)
   ```python
   # Input:  {"actors": ["a", "b", "c"], "current": 2}
   # Output: {"actors": ["c", "d"], "current": 0}  # ERROR: Erased "a", "b"
   ```

2. **Modify already-processed actor names**
   ```python
   # Input:  {"actors": ["a", "b", "c"], "current": 1}
   # Output: {"actors": ["a-new", "b", "c"], "current": 1}  # ERROR: Modified "a"
   ```

3. **Change current position to different actor**
   ```python
   # Input:  {"actors": ["a", "b", "c"], "current": 0}  # Points to "a"
   # Output: {"actors": ["a", "b", "c"], "current": 1}  # ERROR: Now points to "b"
   ```

### Validation

The runtime validates all output envelopes (when `ASYA_ENABLE_VALIDATION=true`):

- All actors from position `0` to `current` must remain unchanged
- The actor at `route.actors[current]` must match the input
- Future actors (after `current`) can be freely modified

**Violations result in `processing_error` and the envelope is sent to `error-end` queue.**

## Response Format

**Success:** `{"status": "ok", "result": <value or list>}`

**Error:** `{"status": "error", "error": "code", "message": "...", "severity": "recoverable|fatal"}`

**Error codes:**
- `oom_error`: RAM OOM (recoverable, retry after 30s)
- `cuda_oom_error`: GPU OOM (recoverable, retry after 60s)
- `processing_error`: User function exception (fatal)
- `invalid_json`: Parse error (fatal)

## Examples

### Payload Mode Examples

**Inference:**
```python
# my_app/handler.py (ASYA_HANDLER_MODE=payload, default)
def predict(payload):
    result = my_model.generate(payload["prompt"])
    return {"generated_text": result}
```

**Fan-out:**
```python
def process(payload):
    # Return list for fan-out
    return [
        {"task": "analyze", "data": payload["text"]},
        {"task": "summarize", "data": payload["text"]}
    ]
```

### Envelope Mode Examples

**Dynamic routing:**
```python
# ASYA_HANDLER_MODE=envelope
def smart_router(envelope):
    payload = envelope["payload"]
    route = envelope["route"]

    # Add conditional actors based on payload
    if payload.get("needs_validation"):
        # Add validator actor after current processing
        route["actors"] = route["actors"] + ["validator", "finalizer"]

    return {
        "payload": {"processed": True, **payload},
        "route": route,
        "headers": envelope.get("headers", {})
    }
```

**Route-aware processing:**
```python
# ASYA_HANDLER_MODE=envelope
def process_with_context(envelope):
    route = envelope["route"]
    current_idx = route["current"]

    # Check if this is the last actor
    is_final = (current_idx == len(route["actors"]) - 1)

    result = {
        "payload": {"is_final_step": is_final},
        "route": route
    }

    if is_final:
        # Add final cleanup actor
        result["route"]["actors"].append("cleanup")

    return result
```

## Testing

```bash
make test         # Run tests
make test-cov     # With coverage
```

## OOM Detection

**RAM OOM:** Triggers GC, returns `oom_error` (recoverable, retry after 30s)

**CUDA OOM:** Clears cache, returns `cuda_oom_error` (recoverable, retry after 60s)

## Deployment

See [docs/architecture/runtime.md](../../docs/architecture/runtime.md) for Kubernetes deployment details
