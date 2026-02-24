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

Note: Socket path is hardcoded to `{ASYA_SOCKET_DIR}/asya-runtime.sock`

## Response Format

**Success:** `{"status": "ok", "result": <value>}`

**Error:** `{"status": "error", "error": "code", "message": "..."}`

**Error codes:**
- `processing_error`: User function exception or handler errors
- `connection_error`: Socket communication failures

## Examples

**Inference:**
```python
# my_app/handler.py
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

## Testing

```bash
make test         # Run tests
make test-cov     # With coverage
```

## Deployment

See [docs/architecture/asya-runtime.md](../../docs/architecture/asya-runtime.md) for Kubernetes deployment details
