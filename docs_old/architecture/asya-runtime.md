# Asya🎭 Runtime

Lightweight Unix socket server for actor processing logic.

> **Full Documentation**: [src/asya-runtime/README.md](../../src/asya-runtime/README.md)

## Overview

Single Python file (stdlib only) handling sidecar-runtime communication via Unix sockets.

## Key Features

- No dependencies (stdlib only)
- Dynamic function loading from any module
- Length-prefix framing (4-byte uint32)
- OOM detection and recovery (RAM + CUDA)
- Functional design (no global state)

## Deployment Internals

The operator automatically manages runtime deployment:

1. **Auto-injection**: Command `["python3", "/opt/asya/asya_runtime.py"]` is injected into the `asya-runtime` container
2. **ConfigMap mount**: Runtime script mounted at `/opt/asya/asya_runtime.py` from ConfigMap
3. **Python requirement**: Container image must have `python3` in PATH (customizable via `workload.pythonExecutable`)

### Container Naming Requirements

**CRITICAL**: The runtime container MUST be named `asya-runtime`. The operator enforces this requirement and rejects AsyncActor CRDs that:
- Use any other container name (e.g., `runtime`, `app`, `worker`)
- Override the `command` field in the `asya-runtime` container

These restrictions prevent security vulnerabilities and ensure the runtime script is properly injected.

### Custom Python Location

Override the Python executable in your Helm chart:

```yaml
workload:
  pythonExecutable: "python3.11"  # Or "/opt/conda/bin/python"
  template:
    spec:
      containers:
      - name: asya-runtime  # MUST be named asya-runtime
        image: your-custom-image
        # DO NOT set command - it will be rejected by operator
```

### Handler Import Resolution

Your handler function must be importable via Python's module system. Use `PYTHONPATH` to ensure the runtime can find your code:

```yaml
# Standalone script at /foo/bar/script.py
env:
- name: PYTHONPATH
  value: "/foo/bar"
- name: ASYA_HANDLER
  value: "script.process"  # Imports from script.py

# Package structure at /app/my_pkg/handler.py
env:
- name: PYTHONPATH
  value: "/app"
- name: ASYA_HANDLER
  value: "my_pkg.handler.predict"
```

## Quick Start

```bash
export ASYA_HANDLER="my_app.handler.predict"
python asya_runtime.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_HANDLER` | _(required)_ | Function path (module.path.function) |
| `ASYA_SOCKET_PATH` | `/tmp/sockets/app.sock` | Unix socket path |
| `ASYA_HANDLER_MODE` | `payload` | Handler mode: `payload` or `envelope` |
| `ASYA_ENABLE_OOM_DETECTION` | `true` | OOM error detection |
| `ASYA_CUDA_CLEANUP_ON_OOM` | `true` | Clear CUDA cache on OOM |

## Handler Modes

Runtime supports two handler modes via `ASYA_HANDLER_MODE`:

### Payload Mode (Default)

**Simple mode**: Handler receives only the payload, runtime manages routing automatically.

```python
def process(payload: dict) -> dict:
    # Process payload, return result
    return {"result": payload["value"] * 2}
```

**Routing Contract**:
- Runtime **automatically increments** `route.current` to point to next actor
- Sidecar sends envelope as-is (no increment)
- Handler doesn't see or modify routing information

### Envelope Mode

**Advanced mode**: Handler receives complete envelope structure and controls routing.

```python
def process(envelope: dict) -> dict:
    # Access payload and route
    payload = envelope["payload"]
    route = envelope["route"]

    # Process and return full envelope with updated route
    return {
        "payload": {"result": payload["value"] * 2},
        "route": {"actors": route["actors"], "current": route["current"] + 1},
        "headers": envelope.get("headers", {})
    }
```

**Routing Contract**:
- Handler **must increment** `route.current` manually
- Handler can modify route (add/remove actors) but must preserve already-processed actors
- Sidecar sends envelope as-is (no increment)

## Routing Responsibility

**Key principle**: Runtime returns complete envelope(s) ready to send with `route.current` already updated.

| Mode | Who increments `current`? | Who modifies route? |
|------|---------------------------|---------------------|
| Payload | Runtime (automatic) | Runtime only |
| Envelope | Handler (manual) | Handler can modify |
| Sidecar | **NEVER** | Never |

## OOM Handling

- **RAM OOM**: Triggers GC, returns `oom_error` (recoverable, retry 30s)
- **CUDA OOM**: Clears cache, returns `cuda_oom_error` (recoverable, retry 60s)

## Deployment

Injected via ConfigMap into user containers. See [src/asya-runtime/README.md](../../src/asya-runtime/README.md) for Kubernetes examples.

## Full Documentation

[src/asya-runtime/README.md](../../src/asya-runtime/README.md)

## Next Steps

- [Sidecar Component](asya-sidecar.md)
- [Gateway Component](asya-gateway.md)
- [Development Guide](../guides/development.md)
