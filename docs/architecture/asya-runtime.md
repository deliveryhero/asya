# Asya Runtime

## Responsibilities

- Load and execute user-defined handler
- Process messages received from sidecar
- Return results to sidecar
- Handle errors gracefully

## How It Works

1. Listen on Unix socket at `/var/run/asya/asya-runtime.sock`
2. Receive message from sidecar
3. Load user handler (function or class)
4. Execute handler with payload (or full message)
5. Return result to sidecar

## Deployment

User defines container with Python code. Operator injects `asya_runtime.py`:

```yaml
containers:

- name: asya-runtime
  image: my-handler:v1
  command: ["python3", "/opt/asya/asya_runtime.py"]  # Injected
  env:
  - name: ASYA_HANDLER
    value: "my_module.MyClass.process"
  - name: ASYA_SOCKET_DIR
    value: /var/run/asya  # Injected
  volumeMounts:
  - name: asya-runtime  # Injected ConfigMap
    mountPath: /opt/asya/asya_runtime.py
    subPath: asya_runtime.py
    readOnly: true
  - name: socket-dir  # Injected
    mountPath: /var/run/asya
```

## Python Executable Resolution

The injector launches the runtime with `python3 /opt/asya/asya_runtime.py`. The bare `python3` is resolved via the container's `PATH` at runtime — the same mechanism that conda, virtualenv, and pyenv all use.

**Most users do not need to configure anything.** As long as `python3` is on your container's `PATH`, it just works.

### How Python is found

1. The injector sets the runtime command to `["python3", "/opt/asya/asya_runtime.py"]`
2. Kubernetes resolves `python3` via the container's `PATH` when starting the process
3. If `ASYA_PYTHONEXECUTABLE` is set on the runtime container, its value replaces `python3` in the command

### Standard approach: ensure `python3` is on PATH

This is how the Python ecosystem works — tools like conda, virtualenv, and pyenv all configure `PATH` so that `python3` resolves to the right binary.

| Image type | `python3` on PATH? | Action needed |
|-----------|-------------------|---------------|
| `python:3.x` | Yes (`/usr/local/bin/python3`) | None |
| `pytorch/pytorch`, `tensorflow/tensorflow` | Yes (conda's `python3`) | None |
| Conda image with activated env | Yes (`/opt/conda/bin/python3`) | None |
| Custom image with `python3` installed | Yes | None |
| Minimal image with only `python` (no `python3`) | **No** | Set `ASYA_PYTHONEXECUTABLE` |
| Custom install without `python3` symlink | **No** | Set `ASYA_PYTHONEXECUTABLE` |

### Last resort: `ASYA_PYTHONEXECUTABLE`

If your container does not have a `python3` binary on `PATH`, set `ASYA_PYTHONEXECUTABLE` to the full path of the Python binary:

```yaml
containers:
- name: asya-runtime
  image: my-custom-image:latest
  env:
  - name: ASYA_PYTHONEXECUTABLE
    value: "/opt/conda/envs/inference/bin/python"
  - name: ASYA_HANDLER
    value: "ml_model.predict"
```

### Python environment variables reference

| Variable | Purpose | Set by Asya? |
|----------|---------|--------------|
| `PATH` | OS-level executable search path; `python3` is resolved via this | No — configured in your Dockerfile or container spec |
| `PYTHONPATH` | Tells Python where to find extra modules/packages | No — set it if your handler is not on the default module path |
| `PYTHONHOME` | Tells Python where its standard library is located | No — rarely needed, managed by conda/venv automatically |
| `VIRTUAL_ENV` | Indicates the active virtual environment path | No — informational, does not affect which binary runs |
| `ASYA_PYTHONEXECUTABLE` | Overrides the Python binary used to launch the runtime | Yes — only needed if `python3` is not on `PATH` |

### Quick decision guide

- **Standard Python image** (`python:3.x`, `pytorch/pytorch`, etc.) → do nothing
- **Conda environment** → ensure the env is activated in your Dockerfile (`conda activate` sets `PATH`); if not, set `ASYA_PYTHONEXECUTABLE`
- **Virtual environment** → ensure the venv is activated in your Dockerfile; if not, set `ASYA_PYTHONEXECUTABLE`
- **Image has `python` but not `python3`** → set `ASYA_PYTHONEXECUTABLE=python`
- **Custom handler import path** → set `PYTHONPATH` (separate from the executable)

## Python Compatibility

**Supports Python 3.7+** for compatibility with legacy AI frameworks.

Runtime uses backward-compatible type hints:
```python
from typing import Dict, List  # Not dict, list
```

## Handler Types

### Function Handler

**Configuration**: `ASYA_HANDLER=module.function`

**Example**:
```python
# handler.py
def process(payload: dict) -> dict:
    return {"result": payload["value"] * 2}
```

### Class Handler

**Configuration**: `ASYA_HANDLER=module.Class.method`

**Example**:
```python
# handler.py
class Processor:
    def __init__(self, model_path: str = "/models/default"):
        self.model = load_model(model_path)  # Init once

    def process(self, payload: dict) -> dict:
        return {"result": self.model.predict(payload)}
```

**Benefits**: Stateful initialization (model loading, preprocessing setup)

**Important**: All `__init__` parameters must have default values for zero-arg instantiation.

```python
# ✅ Correct - all params have defaults
class Processor:
    def __init__(self, model_path: str = "/models/default"):
        self.model = load_model(model_path)

# ❌ Wrong - param without default
class Processor:
    def __init__(self, model_path: str):  # Missing default!
        self.model = load_model(model_path)
```

## Handler Modes

### Payload Mode (Default)

**Configuration**: `ASYA_HANDLER_MODE=payload`

Handler receives only payload, headers/route preserved automatically:

```python
def process(payload: dict) -> dict:
    return {"result": ...}  # Single value or list for fan-out
```

Runtime automatically:

- Increments `route.current`
- Preserves `headers`
- Creates new message with mutated payload

### Envelope Mode

**Configuration**: `ASYA_HANDLER_MODE=envelope`

Handler receives full message structure:

```python
def process(envelope: dict) -> dict:
    # Modify route dynamically
    envelope["route"]["actors"].append("extra-step")
    envelope["route"]["current"] += 1
    envelope["payload"]["processed"] = True
    return envelope
```

**Use case**: Dynamic routing, route modification

## Response Patterns

### Single Response

```python
return {"processed": True}
```

Sidecar creates one message, routes to next actor.

### Fan-Out

```python
return [{"chunk": 1}, {"chunk": 2}, {"chunk": 3}]
```

Sidecar creates multiple messages (one per item).

### Abort

```python
return None  # or []
```

Sidecar routes message to `happy-end` (no more processing).

### Error

```python
raise ValueError("Invalid input")
```

Runtime catches exception, creates error response with detailed traceback:

```python
[{
  "error": "processing_error",
  "details": {
    "message": "Invalid input",
    "type": "ValueError",
    "traceback": "Traceback (most recent call last):\n  File ..."
  }
}]
```

**Error codes**:

- `processing_error`: Handler exception (any unhandled error)
- `msg_parsing_error`: Invalid JSON or message structure
- `connection_error`: Socket/network issues

Sidecar receives error response and routes message to `error-end`.

## Route Modification Rules

Handlers in envelope mode can modify routes but **MUST preserve already-processed steps**:

✅ **Allowed**:

- Add future steps: `["a","b","c"]` → `["a","b","c","d"]` (at current=0)
- Replace future steps: `["a","b","c"]` → `["a","x","y"]` (at current=0)

❌ **Forbidden**:

- Erase processed steps: `["a","b","c"]` → `["c"]` at current=2
- Modify processed actor names: `["a","b","c"]` → `["a-new","b","c"]` at current=1

**Validation**: Runtime validates `route.actors[0:current+1]` unchanged.

## `asya_runtime.py` via ConfigMap

**Source**: `src/asya-runtime/asya_runtime.py` (single file, no dependencies)

**Deployment**:
1. Operator reads `asya_runtime.py` at runtime (via `ASYA_RUNTIME_SCRIPT_PATH` or default)
2. Stores content in ConfigMap
3. Mounts ConfigMap into actor pods at `/opt/asya/asya_runtime.py`

**Symlinks** (for testing):

- `src/asya-operator/internal/controller/runtime_symlink/asya_runtime.py` → Operator reads
- `testing/integration/operator/testdata/runtime_symlink/asya_runtime.py` → Tests use

**IMPORTANT**: Symlinks automatically reflect changes to source file. No manual sync needed.

## Readiness Probe

Runtime signals readiness via separate mechanism:

```yaml
readinessProbe:
  exec:
    command: ["sh", "-c", "test -S /var/run/asya/asya-runtime.sock && test -f /var/run/asya/runtime-ready"]
```

Runtime creates `/var/run/asya/runtime-ready` file after handler initialization.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_HANDLER` | (required) | Handler path (`module.Class.method`) |
| `ASYA_HANDLER_MODE` | `payload` | Mode: `payload` or `envelope` |
| `ASYA_PYTHONEXECUTABLE` | `python3` | Python binary path for launching the runtime |
| `ASYA_SOCKET_DIR` | `/var/run/asya` | Unix socket directory (internal testing only) |
| `ASYA_SOCKET_NAME` | `asya-runtime.sock` | Socket filename (internal testing only) |
| `ASYA_SOCKET_CHMOD` | `0o666` | Socket permissions in octal (empty = skip chmod) |
| `ASYA_CHUNK_SIZE` | `65536` | Socket read chunk size in bytes |
| `ASYA_ENABLE_VALIDATION` | `true` | Enable message validation |
| `ASYA_LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

**Note**: `ASYA_SOCKET_DIR` and `ASYA_SOCKET_NAME` are for internal testing only. DO NOT set in production - socket path is managed by operator.

## Examples

**Data processing**:
```python
def process(payload: dict) -> dict:
    data = fetch_data(payload["id"])
    return {**payload, "data": data}
```

**AI inference**:
```python
class LLMInference:
    def __init__(self):
        self.model = load_llm("/models/llama3")

    def process(self, payload: dict) -> dict:
        response = self.model.generate(payload["prompt"])
        return {**payload, "response": response}
```

**Dynamic routing**:
```python
def process(envelope: dict) -> dict:
    if envelope["payload"]["priority"] == "high":
        envelope["route"]["actors"].insert(
            envelope["route"]["current"] + 1,
            "priority-handler"
        )
    envelope["route"]["current"] += 1
    return envelope
```
