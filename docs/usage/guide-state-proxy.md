<!-- Type: Usage Guide -->
# Using the State Proxy

How to read and write persistent state from your actor handlers using standard Python file operations.

---

## What is the state proxy?

The state proxy gives your actor handlers **persistent state** via the filesystem — without StatefulSets, without volumes, and without installing an SDK.

Your handler code reads and writes files under `/state/`:

```python
# Read state
with open("/state/model.bin", "rb") as f:
    weights = f.read()

# Write state
with open("/state/cache/result.json", "w") as f:
    f.write(json.dumps(result))
```

Behind the scenes, the Asya runtime intercepts these file operations and forwards them to a storage backend (S3, Redis) via a sidecar connector. Your handler sees a filesystem; the platform stores data in object storage or a key-value store.

**Key benefits**:
- No imports, no SDK — just standard Python `open()`, `os.stat()`, `os.listdir()`
- Actors remain stateless Deployments (no StatefulSets, no PVCs)
- Storage backend is swappable (S3, Redis, GCS) without changing handler code
- Conflict-free or CAS guarantees depending on connector choice

---

## How it works

When you configure `stateProxy` in your AsyncActor spec, the Crossplane composition:

1. Adds a connector sidecar container to the pod (one per mount)
2. Mounts a shared Unix socket volume between the runtime and connectors
3. Sets `ASYA_STATE_PROXY_MOUNTS` env var on the runtime container

At startup, the runtime patches Python builtins (`open`, `os.stat`, `os.listdir`, etc.) to intercept file operations on configured mount paths and translate them to HTTP requests over Unix sockets to the connector sidecars.

```
Handler code
  open("/state/weights/model.bin", "rb")
       │
       ▼
  Patched builtins.open (runtime hooks)
       │ HTTP GET /keys/model.bin
       ▼
  Connector sidecar (s3-buffered-lww)
       │
       ▼
  Storage backend (S3)
```

---

## Configuration

Add `stateProxy` entries to your AsyncActor spec:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: model-inference
  namespace: prod
spec:
  actor: model-inference

  stateProxy:
    - name: weights          # Unique mount identifier
      mount:
        path: /state/weights # Path in runtime container
      writeMode: buffered    # buffered (default) or passthrough
      connector:
        image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
        env:
          - name: STATE_BUCKET
            value: my-model-weights
          - name: AWS_REGION
            value: us-east-1
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
```

### Multiple mounts

You can configure multiple mounts with different backends:

```yaml
stateProxy:
  - name: weights
    mount:
      path: /state/weights
    connector:
      image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
      env:
        - name: STATE_BUCKET
          value: my-model-weights

  - name: cache
    mount:
      path: /state/cache
    connector:
      image: ghcr.io/deliveryhero/asya-state-proxy-redis-buffered-cas:v1.0.0
      env:
        - name: REDIS_URL
          value: redis://redis.default:6379/0
```

Each mount is independent — you can mix S3 and Redis, or use different buckets for different data types.

---

## Basic usage

### Reading state

```python
import json

async def my_handler(payload: dict):
    # Check if state exists
    import os
    if os.path.exists("/state/cache/config.json"):
        with open("/state/cache/config.json") as f:
            config = json.load(f)
    else:
        config = {"default": True}

    # Use the config
    result = await process(payload, config)
    payload["result"] = result
    yield payload
```

### Writing state

```python
import json

async def my_handler(payload: dict):
    result = await compute(payload)

    # Cache the result
    with open("/state/cache/result.json", "w") as f:
        json.dump(result, f)

    payload["result"] = result
    yield payload
```

### Binary data

```python
async def my_handler(payload: dict):
    # Read binary data
    with open("/state/weights/model.bin", "rb") as f:
        weights = f.read()

    model = load_model_from_bytes(weights)
    result = await model.predict(payload["input"])

    payload["result"] = result
    yield payload
```

---

## Common patterns

### 1. Caching model weights

Load model weights from state on first call, cache in memory:

```python
class Inference:
    def __init__(self):
        self.model = None  # Lazy-loaded

    async def process(self, payload: dict):
        if self.model is None:
            # Load weights from state proxy
            with open("/state/weights/llama3.bin", "rb") as f:
                weights = f.read()
            self.model = load_model(weights)

        result = await self.model.predict(payload["prompt"])
        payload["response"] = result
        yield payload
```

**Why this works**: The class handler is instantiated once per pod. `self.model` persists across messages, so weights are loaded only on the first call.

### 2. Storing conversation history

Append to conversation state for multi-turn agents:

```python
import json
import os

async def conversational_agent(payload: dict):
    session_id = payload["session_id"]
    state_path = f"/state/sessions/{session_id}.json"

    # Load existing conversation
    if os.path.exists(state_path):
        with open(state_path) as f:
            conversation = json.load(f)
    else:
        conversation = {"messages": []}

    # Add user message
    conversation["messages"].append({
        "role": "user",
        "content": payload["message"]
    })

    # Call LLM with full history
    response = await llm.chat(conversation["messages"])

    # Append assistant response
    conversation["messages"].append({
        "role": "assistant",
        "content": response
    })

    # Persist updated conversation
    with open(state_path, "w") as f:
        json.dump(conversation, f)

    payload["response"] = response
    yield payload
```

### 3. Result caching with TTL

Cache expensive computations with a timestamp:

```python
import json
import os
from datetime import datetime, timedelta

async def cached_computation(payload: dict):
    cache_key = payload["input_hash"]
    cache_path = f"/state/cache/{cache_key}.json"

    # Check cache
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            cached = json.load(f)

        cached_at = datetime.fromisoformat(cached["timestamp"])
        if datetime.utcnow() - cached_at < timedelta(hours=1):
            # Cache hit
            payload["result"] = cached["result"]
            payload["cached"] = True
            yield payload
            return

    # Cache miss — compute
    result = await expensive_operation(payload["input"])

    # Store in cache
    with open(cache_path, "w") as f:
        json.dump({
            "result": result,
            "timestamp": datetime.utcnow().isoformat()
        }, f)

    payload["result"] = result
    payload["cached"] = False
    yield payload
```

### 4. Listing and deleting state

```python
import os

async def cleanup_handler(payload: dict):
    # List all cache files
    cache_files = os.listdir("/state/cache/")

    deleted = []
    for filename in cache_files:
        path = f"/state/cache/{filename}"

        # Delete old files (simple heuristic: starts with "temp-")
        if filename.startswith("temp-"):
            os.remove(path)
            deleted.append(filename)

    payload["deleted_files"] = deleted
    yield payload
```

---

## LWW vs CAS guarantees

Asya provides two conflict-resolution strategies via different connector images:

### Last-Write-Wins (LWW)

Image suffix: `s3-buffered-lww`, `s3-passthrough`

**Behavior**: Writes always overwrite the existing object. No conflict detection.

**Use when**:
- State is written by a **single actor instance** (Deployment with `replicas: 1`)
- You don't care about lost updates (e.g., ephemeral cache)
- Simplicity is more important than correctness

**Example**: Model weights loaded at startup (read-only after initialization).

### Check-And-Set (CAS)

Image suffix: `s3-buffered-cas`, `redis-buffered-cas`

**Behavior**: On write, the connector checks if the object has changed since the last read. If it has, the write fails with `FileExistsError`.

**Use when**:
- Multiple actor replicas may write to the same key
- You need to detect concurrent modifications
- You can handle write conflicts in your handler code

**Example**: Conversation history updated by multiple replicas.

**Handler code**:

```python
import json
import os

async def update_state_with_cas(payload: dict):
    state_path = "/state/shared/counter.json"

    for attempt in range(3):  # Retry loop
        try:
            # Read current state
            if os.path.exists(state_path):
                with open(state_path) as f:
                    state = json.load(f)
            else:
                state = {"count": 0}

            # Modify
            state["count"] += 1

            # Write (fails if modified externally since read)
            with open(state_path, "w") as f:
                json.dump(state, f)

            break  # Success

        except FileExistsError:
            # CAS conflict — retry
            continue
    else:
        raise RuntimeError("Failed to update state after 3 retries")

    payload["new_count"] = state["count"]
    yield payload
```

**CAS guarantees**: With `s3-buffered-cas` or `redis-buffered-cas`, concurrent writes to the same key are serialized — one succeeds, others fail with `FileExistsError`. Your handler must retry.

**LWW behavior**: With `s3-buffered-lww`, the same code would allow concurrent writes — both would succeed, but one would silently overwrite the other.

---

## Write modes

Write mode controls how data is buffered before being sent to the storage backend.

### buffered

`writeMode: buffered` (default)

Data is collected in memory (or spilled to disk above 4 MiB) and sent as a single `PUT` when the file is closed.

**Pros**:
- Supports `seek()` and `tell()` before close
- Connector receives `Content-Length` upfront (required by some S3 SDKs)

**Cons**:
- Not suitable for very large files (spills to disk)

**Use for**: Small-to-medium files (model configs, conversation history, cache entries).

### passthrough

`writeMode: passthrough`

Data is sent to the connector immediately on each `write()` call using HTTP chunked transfer encoding.

**Pros**:
- No buffering — suitable for very large files
- Streaming writes (e.g., model weights downloaded from external source)

**Cons**:
- Does not support `seek()` or `tell()`

**Use for**: Large files (multi-GB model weights, video files, large datasets).

**Configuration**:

```yaml
stateProxy:
  - name: weights
    mount:
      path: /state/weights
    writeMode: passthrough  # Stream large files
    connector:
      image: ghcr.io/deliveryhero/asya-state-proxy-s3-passthrough:v1.0.0
      env:
        - name: STATE_BUCKET
          value: my-large-weights
```

---

## Library compatibility

The state proxy works with **pure-Python libraries** that use `builtins.open()`. Libraries with C extensions that perform system-level I/O (e.g., pandas parquet, PyTorch, NumPy) require a workaround.

### Works out of the box

```python
import json, csv, pickle, yaml

# json
with open("/state/meta/config.json") as f:
    config = json.load(f)

# csv
with open("/state/meta/data.csv") as f:
    rows = list(csv.reader(f))

# pickle
with open("/state/meta/model.pkl", "rb") as f:
    model = pickle.load(f)

# yaml (PyYAML)
with open("/state/meta/spec.yaml") as f:
    spec = yaml.safe_load(f)
```

### Requires BytesIO workaround

Libraries with C extensions (pandas parquet, PyTorch, NumPy) bypass Python-level `open()`:

```python
import io
import pandas as pd
import torch
import numpy as np

# pandas parquet
with open("/state/meta/data.parquet", "rb") as f:
    df = pd.read_parquet(io.BytesIO(f.read()))

# torch
with open("/state/weights/model.pt", "rb") as f:
    model = torch.load(io.BytesIO(f.read()))

# numpy
with open("/state/meta/array.npy", "rb") as f:
    arr = np.load(io.BytesIO(f.read()))
```

**Why**: These libraries use C-level system calls (`open(2)`, `read(2)`) that bypass the Python builtin patches. Reading through `open()` first, then wrapping in `io.BytesIO`, forces the data through the patched path.

---

## Error handling

HTTP error responses from the connector are mapped to standard Python exceptions:

```python
import os

async def my_handler(payload: dict):
    try:
        with open("/state/cache/result.json", "rb") as f:
            cached = json.load(f)
    except FileNotFoundError:
        # Cache miss
        cached = None
    except PermissionError:
        # Connector denied access (e.g., IAM permissions)
        raise
    except FileExistsError:
        # CAS conflict (s3-buffered-cas, redis-buffered-cas)
        # Retry or fail
        raise
```

| Exception | HTTP status | Meaning |
|-----------|-------------|---------|
| `FileNotFoundError` | 404 | Key does not exist |
| `PermissionError` | 403 | Connector lacks access (IAM, Redis ACL) |
| `FileExistsError` | 409 | CAS conflict (key modified since read) |
| `OSError` | 500 | Backend error (S3 throttling, Redis down) |
| `ConnectionError` | 503 | Connector unavailable |
| `TimeoutError` | 504 | Backend timeout |

---

## Limitations

The state proxy patches Python builtins at the interpreter level. This intercepts Python-level file operations but cannot intercept C-level system calls.

### Not patched

| API | Workaround |
|-----|-----------|
| `os.open()` | Use `builtins.open()` instead |
| `os.rename()` | Read + write + delete manually |
| `os.walk()` | Use `os.listdir()` recursively |
| `pathlib.Path.read_bytes()` | Use `open(path, "rb").read()` |
| `shutil.copy2()` | Fails on metadata; use `shutil.copyfileobj()` |

### Filesystem metadata

`os.stat()` returns synthetic metadata:

| Field | Value | Real? |
|-------|-------|-------|
| `st_size` | Actual content size | ✅ |
| `st_mode` | `0o644` (file) / `0o755` (dir) | ❌ Synthetic |
| `st_mtime` | `0` | ❌ Not available |

Libraries that depend on modification times (e.g., caching based on `mtime`) will not work correctly.

### Directory semantics

The state proxy is a **flat key-value store**, not a real filesystem. Paths like `/state/meta/subdir/file.txt` are stored as the key `subdir/file.txt` — there is no actual `subdir/` directory.

- `os.makedirs()` is a no-op for mount paths
- `os.listdir()` uses prefix-based listing to simulate directory entries

---

## See also

| Topic | Document |
|-------|----------|
| State proxy architecture | [docs/reference/components/core-state-proxy.md](../reference/components/core-state-proxy.md) |
| Available connector images | [docs/reference/components/core-state-proxy.md](../reference/components/core-state-proxy.md#connector-types) |
| Crossplane composition rendering | [docs/reference/components/core-state-proxy.md](../reference/components/core-state-proxy.md#crossplane-composition-step) |

---
**Platform configuration**: To configure state proxy storage backends, see [setup/guide-state-proxy.md](../setup/guide-state-proxy.md).
