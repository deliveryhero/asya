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
| `ASYA_ENABLE_VALIDATION` | `true` | Enable message validation (disable for performance) |

Note: Socket path is hardcoded to `{ASYA_SOCKET_DIR}/asya-runtime.sock`

## Handler Modes

### Payload Mode (Default)

Simple mode where handlers work only with payloads. Routes and headers are preserved automatically.

```python
def your_function(payload: dict) -> dict:
    """Process payload and return result."""
    result = process(payload)
    return {"result": result}
```

### Envelope Mode (Advanced)

Full access to envelope structure (payload, route, headers). Required for dynamic routing.

```python
# Set ASYA_HANDLER_MODE=envelope
def your_function(envelope: dict) -> dict:
    """Process full envelope with access to route."""
    payload = envelope["payload"]
    route = envelope["route"]  # {"prev": [...], "curr": "actor-name", "next": [...]}
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

1. **Add future steps** (`next` list)
   ```python
   # Input:  {"prev": ["a"], "curr": "b", "next": ["c"]}
   # Output: {"prev": ["a"], "curr": "b", "next": ["c", "d", "e"]}  # Added d, e
   ```

2. **Replace future steps** (`next` list)
   ```python
   # Input:  {"prev": [], "curr": "a", "next": ["b", "c"]}
   # Output: {"prev": [], "curr": "a", "next": ["x", "y"]}  # Replaced b, c with x, y
   ```

3. **Keep route unchanged**
   ```python
   # Input:  {"prev": [], "curr": "a", "next": ["b"]}
   # Output: {"prev": [], "curr": "a", "next": ["b"]}  # Same
   ```

### ❌ Forbidden Operations

1. **Modify already-processed steps** (`prev` list)
   ```python
   # Input:  {"prev": ["a", "b"], "curr": "c", "next": []}
   # Output: {"prev": ["a"], "curr": "c", "next": []}  # ERROR: Erased "b" from prev
   ```

2. **Modify current actor name** (`curr` field)
   ```python
   # Input:  {"prev": ["a"], "curr": "b", "next": ["c"]}
   # Output: {"prev": ["a"], "curr": "b-new", "next": ["c"]}  # ERROR: Modified curr
   ```

### Validation

The runtime validates all output messages (when `ASYA_ENABLE_VALIDATION=true`):

- `prev` list must remain unchanged from input to output
- `curr` field must remain unchanged from input to output
- `next` list can be freely modified

**Violations result in `processing_error` and the message is sent to `x-sump` queue.**

## Response Format

**Success:** `{"status": "ok", "result": <value>}`

**Error:** `{"status": "error", "error": "code", "message": "..."}`

**Error codes:**
- `processing_error`: User function exception or handler errors
- `connection_error`: Socket communication failures

## Examples

### Payload Mode Examples

**Inference:**
```python
# my_app/handler.py (ASYA_HANDLER_MODE=payload, default)
def predict(payload):
    result = my_model.generate(payload["prompt"])
    return {"generated_text": result}
```

**Fan-out (yield):**
```python
def process(payload):
    # Yield multiple outputs for fan-out
    for item in payload["items"]:
        yield {"processed": item}
```

**Note**: Returning a list does NOT trigger fan-out. A returned list is treated as a single payload value.

### Envelope Mode Examples

**Dynamic routing:**
```python
# ASYA_HANDLER_MODE=envelope
def smart_router(envelope):
    payload = envelope["payload"]
    route = envelope["route"]

    # Add conditional actors based on payload
    if payload.get("needs_validation"):
        # Extend next steps with additional actors
        route["next"] = route["next"] + ["validator", "finalizer"]

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

    # Check if this is the last actor
    is_final = len(route["next"]) == 0

    result = {
        "payload": {"is_final_step": is_final},
        "route": route
    }

    if is_final:
        # Add final cleanup actor
        result["route"]["next"].append("cleanup")

    return result
```

## Testing

```bash
make test         # Run tests
make test-cov     # With coverage
```

## Deployment

See [docs/architecture/asya-runtime.md](../../docs/architecture/asya-runtime.md) for Kubernetes deployment details
