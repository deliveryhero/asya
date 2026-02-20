---
title: Stateful Actors — Transparent State Access
status: open
priority: 2 # medium
type: epic
---

## Summary

Asya actors access persistent state through **transparent filesystem emulation**. Actors read and write files under designated mount paths (e.g., `./cache/`, `./s3data/`), and `asya_runtime.py` intercepts these operations, translating them to requests against a **connector sidecar** that implements the actual storage backend (S3, GCS, Redis, NATS KV, etc.).

All actors remain **stateless Deployments** — there are no StatefulSets, no per-pod storage, no shard affinity. The state is always external, accessed through a uniform filesystem interface.

---

## Motivation

Asya actors are stateless: each message is processed independently. This works for single-request pipelines but breaks for use cases that need persistent cross-message or cross-actor data:

- **Agentic per-user context storage**: An AI agent accumulates context across a conversation; each message must read prior context and write updated state
- **Media file storage**: Actors produce or consume images, audio, video that must be stored durably
- **Fan-in stateful aggregation**: Partial results from fan-out converge into shared state (see [ADR-9](#adr-9-fan-in-as-crew-actor-using-state-mounts))
- **Session files**: Intermediate artifacts (model checkpoints, temp data) that persist across messages

Today, actors that need state must directly import and manage database clients (boto3 for S3, redis-py for Redis, etc.). This creates boilerplate, ties handler code to specific backends, and breaks local development (handlers don't work without a live database).

### Requirements

- **Transparent access**: Handlers use standard Python file I/O (`open()`, `os.path.exists()`, `pathlib`) — no special imports, no SDK knowledge
- **Backend-agnostic**: The same handler code works with S3, GCS, Redis, NATS KV, or a local directory
- **Local dev parity**: Without configuration, mount paths are real directories — handlers work locally with zero setup
- **Modular backends**: Each storage backend is a separate connector sidecar — no backend logic in `asya_runtime.py` or `asya-sidecar`
- **Streaming support**: Large files (media, model weights) are streamed, not buffered entirely in memory
- **No framework bloat**: `asya_runtime.py` remains a single file with zero dependencies

---

## Architecture

```
User container                          Connector sidecar(s)
+-----------------------------+
| Handler code                |
|   open("./s3data/key", "w") |
|   os.path.exists("./cache/k")|
+----------+------------------+
           |
           v
+----------+------------------+
| asya_runtime.py             |
|   - patches builtins.open,  |    Unix socket          +------------------------+
|     os.stat, os.listdir,    |---(/var/run/asya/state/--| asya-connector-s3      |---> S3
|     os.scandir, os.unlink   |    s3data.sock)         +------------------------+
|   - translates path ops to  |
|     HTTP over Unix socket   |    Unix socket          +------------------------+
|   - thin protocol client    |---(/var/run/asya/state/--| asya-connector-redis   |---> Redis
|     (~80-100 lines)         |    cache.sock)          +------------------------+
+-----------------------------+

+-----------------------------+
| asya-sidecar (Go)           |   (unchanged — message routing only)
+-----------------------------+
```

### Component responsibilities

| Component | Responsibility |
|-----------|---------------|
| `asya_runtime.py` | Patches Python file I/O for configured mount paths; translates operations to HTTP requests over Unix socket. ~80-100 lines added, zero new dependencies. |
| `asya-connector-*` | Separate container image per backend (`asya-connector-s3`, `asya-connector-redis`, `asya-connector-nats`, etc.). Implements a standard HTTP-over-Unix-socket protocol. Owns all backend-specific logic, SDKs, and credentials. |
| `asya-sidecar` | Unchanged. Message routing only. |
| `asya-injector` | Adds connector sidecar containers and Unix socket volumes based on the actor's `state` spec. |
| Crossplane XRD | New optional `state` field defining mount configurations. |

### Why separate connector sidecars?

- **Modularity**: Each connector is a focused, single-purpose container. Adding a new backend means building a new image, not modifying the sidecar.
- **Independent lifecycle**: Connectors can be versioned and updated independently of the sidecar and runtime.
- **Credential isolation**: Each connector manages its own credentials (IAM roles, Redis auth, etc.) without exposing them to the runtime or sidecar.
- **User-extensible**: Users can build custom connectors implementing the same protocol for proprietary storage systems.

---

## Protocol: HTTP over Unix Socket

Each connector listens on a Unix socket at `/var/run/asya/state/{mount-name}.sock` and implements a RESTful API:

```
GET    /keys/{key}                              -> 200 + body stream (read)
PUT    /keys/{key}                              -> stream request body (write)
HEAD   /keys/{key}                              -> 204 exists / 404 not found
DELETE /keys/{key}                              -> 204 deleted
GET    /keys/?prefix={p}                        -> 200 + JSON array of keys
GET    /keys/?prefix={p}&delimiter=/            -> 200 + JSON {keys: [], prefixes: []}
GET    /keys/?prefix={p}&delimiter=/&limit={n}  -> 200 + limited listing
```

Response headers for `GET /keys/{key}`:
- `Content-Length`: object size (when known)
- `Content-Type`: `application/octet-stream`

Response headers for `HEAD /keys/{key}`:
- `Content-Length`: object size
- `X-Exists`: `true`

This protocol is intentionally simple — any language can implement a connector. No custom serialization, no RPC frameworks. Standard HTTP semantics.

---

## Configuration

### AsyncActor spec

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-agent
spec:
  actor: my-agent
  transport: sqs
  state:
    - backend: s3
      config:
        bucket: my-bucket
        prefix: artifacts/
        region: us-east-1
      mount: ./s3data
    - backend: redis
      config:
        endpoint: redis://cache:6379/0
      mount: ./cache
  workload:
    kind: Deployment
    template:
      spec:
        containers:
          - name: asya-runtime
            image: my-agent:latest
            env:
              - name: ASYA_HANDLER
                value: "agent.handle"
```

### Injected environment variables

The injector translates `state` spec into environment variables for the runtime:

```
ASYA_STATE_MOUNTS=./s3data,./cache
ASYA_STATE_MOUNT_s3data_SOCKET=/var/run/asya/state/s3data.sock
ASYA_STATE_MOUNT_cache_SOCKET=/var/run/asya/state/cache.sock
```

The runtime only needs mount paths and socket paths. It does not know or care about backends, buckets, or credentials.

### Injected connector sidecars

The injector adds connector containers based on the `state` spec:

```yaml
# Auto-injected by asya-injector
- name: state-s3data
  image: asya-connector-s3:latest
  env:
    - name: STATE_BUCKET
      value: "my-bucket"
    - name: STATE_PREFIX
      value: "artifacts/"
    - name: AWS_REGION
      value: "us-east-1"
  volumeMounts:
    - name: state-sockets
      mountPath: /var/run/asya/state

- name: state-cache
  image: asya-connector-redis:latest
  env:
    - name: STATE_ENDPOINT
      value: "redis://cache:6379/0"
  volumeMounts:
    - name: state-sockets
      mountPath: /var/run/asya/state
```

---

## Python Interception Layer

### Activation

At startup, before loading the handler:

```python
# In asya_runtime.py, during initialization
state_mounts = os.environ.get("ASYA_STATE_MOUNTS")
if state_mounts:
    _install_state_hooks(state_mounts)
```

When `ASYA_STATE_MOUNTS` is unset, no patching occurs. Mount paths are real directories. Handlers work locally with zero configuration.

### What gets patched

Six functions, covering all standard Python file I/O entry points:

| Python API | Patch target | State operation |
|------------|-------------|-----------------|
| `open(path, "r"/"rb")`, `pathlib.Path.read_text/read_bytes` | `builtins.open` | `GET /keys/{key}` — returns streaming file-like object |
| `open(path, "w"/"wb")`, `pathlib.Path.write_text/write_bytes` | `builtins.open` | Buffered write, `PUT /keys/{key}` on `close()` |
| `os.path.exists(path)`, `pathlib.Path.exists()` | `os.stat` | `HEAD /keys/{key}` — 204/404 |
| `os.listdir(path)` | `os.listdir` | `GET /keys/?prefix=...&delimiter=/` |
| `pathlib.Path.iterdir()`, `os.scandir(path)` | `os.scandir` | `GET /keys/?prefix=...&delimiter=/` |
| `os.remove(path)`, `pathlib.Path.unlink()` | `os.unlink` | `DELETE /keys/{key}` |
| `os.makedirs(path)` | `os.makedirs` | No-op for state paths (prefixes are implicit) |

The key to catching `pathlib` operations: `pathlib.Path.open()` delegates to `builtins.open`, and `pathlib.Path.exists()` delegates to `os.stat`. Patching the low-level functions catches all high-level wrappers.

`os.fspath()` is used to normalize all path arguments (`str`, `bytes`, `os.PathLike`) before mount matching.

### Streaming reads

`http.client.HTTPResponse` natively supports `read(size)` for chunked reading. The patched `open()` returns a file-like wrapper around the HTTP response:

```python
class _StateReadFile:
    """File-like object backed by streaming GET from connector."""

    def __init__(self, response):
        self._resp = response  # http.client.HTTPResponse

    def read(self, size=-1):
        return self._resp.read(size)

    def readline(self):
        return self._resp.readline()

    def readlines(self):
        return self._resp.readlines()

    def __iter__(self):
        return self

    def __next__(self):
        line = self._resp.readline()
        if not line:
            raise StopIteration
        return line

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._resp.close()

    @property
    def closed(self):
        return self._resp.closed
```

User code — completely standard Python, including chunked reads for large files:

```python
# Small file — read all at once
with open("./s3data/config.json") as f:
    config = json.load(f)

# Large file — chunked streaming
with open("./s3data/media/video.mp4", "rb") as f:
    while chunk := f.read(8192):
        process_chunk(chunk)

# Line-by-line iteration
with open("./s3data/logs/events.jsonl") as f:
    for line in f:
        event = json.loads(line)
```

### Streaming writes

Writes buffer to a `SpooledTemporaryFile` (in-memory up to a threshold, then spills to disk) and flush to the connector on `close()`:

```python
class _StateWriteFile:
    """File-like object that buffers writes, flushes to connector on close."""

    def __init__(self, sock_path, key, mode):
        self._sock_path = sock_path
        self._key = key
        self._buf = io.SpooledTemporaryFile(
            max_size=4 * 1024 * 1024,  # 4MB in-memory, then spill to disk
            mode=mode,
        )

    def write(self, data):
        return self._buf.write(data)

    def writelines(self, lines):
        self._buf.writelines(lines)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._buf.seek(0)
        conn = _unix_http_connection(self._sock_path)
        size = self._buf.seek(0, 2)  # seek to end for size
        self._buf.seek(0)
        conn.request("PUT", f"/keys/{self._key}", body=self._buf,
                      headers={"Content-Length": str(size)})
        resp = conn.getresponse()
        if resp.status >= 400:
            raise IOError(f"State write failed: {resp.status} {resp.reason}")
        self._buf.close()
```

The connector receives the body stream and uploads to the backend. For S3, the connector can use multipart upload for large objects.

User code:

```python
# Small write
with open("./s3data/results/output.json", "w") as f:
    json.dump(result, f)

# Large write — data streams through SpooledTemporaryFile
with open("./s3data/media/generated.png", "wb") as f:
    for chunk in generate_image_chunks():
        f.write(chunk)
```

### Unix socket HTTP client

The runtime connects to connectors using `http.client` over Unix sockets. Python stdlib supports this via a custom connection class (~20 lines):

```python
class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, sock_path):
        super().__init__("localhost")
        self._sock_path = sock_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._sock_path)
```

### Directories

Directories are virtual. They correspond to key prefixes in the backend (S3 prefixes, Redis key prefixes with `SCAN MATCH`).

| Operation | Behavior |
|-----------|----------|
| `os.makedirs("./cache/users/123/")` | No-op (prefixes are implicit) |
| `os.listdir("./cache/users/")` | Prefix scan with delimiter: returns immediate children |
| `os.path.isdir("./cache/users/")` | `GET /keys/?prefix=users/&delimiter=/&limit=1` — true if any keys/prefixes exist |
| `os.path.isfile("./cache/users/123")` | `HEAD /keys/users/123` — true if key exists |
| `os.rmdir("./cache/users/")` | No-op or error (directories don't exist as objects) |

Example — listing and iterating:

```python
# List immediate children of a "directory"
entries = os.listdir("./s3data/users/")
# -> ["alice", "bob", "carol"]  (could be files or "subdirectories")

# Walk a tree (os.walk delegates to listdir + isdir)
for root, dirs, files in os.walk("./s3data/users/"):
    for f in files:
        path = os.path.join(root, f)
        with open(path) as fh:
            process(fh.read())
```

For S3, `GET /keys/?prefix=users/&delimiter=/` returns:
```json
{"keys": ["users/alice.json"], "prefixes": ["users/bob/", "users/carol/"]}
```

The runtime translates `prefixes` into directory entries and `keys` into file entries.

For Redis, `SCAN MATCH users:*` with key-part parsing achieves the same semantics.

---

## Latency Characteristics

| Operation | Unix socket overhead | Backend latency (typical) | Total |
|-----------|---------------------|--------------------------|-------|
| `open() + read()` (small) | ~0.05ms | Redis: <1ms, S3: 5-50ms | <1ms (Redis), 5-50ms (S3) |
| `open() + read()` (stream) | ~0.05ms | Dominated by transfer time | Backend-dependent |
| `open() + write() + close()` | ~0.05ms | Redis: <1ms, S3: 10-100ms | <1ms (Redis), 10-100ms (S3) |
| `os.path.exists()` | ~0.05ms | Redis: <1ms, S3: 5-20ms | <1ms (Redis), 5-20ms (S3) |
| `os.listdir()` | ~0.05ms | Redis: 1-10ms, S3: 10-100ms | 1-10ms (Redis), 10-100ms (S3) |

For actor workloads (LLM inference takes 500-5000ms per call), these latencies are negligible.

---

## Limitations

### Write-on-close semantics

Data is sent to the connector (and ultimately to the backend) when the file is closed, not on each `write()` call. A crash mid-write loses uncommitted data. This is acceptable for the target use cases (context storage, media, session data) where messages are processed atomically.

### No filesystem metadata

`os.stat()` returns synthetic values:
- `st_size`: from backend (`Content-Length` header)
- `st_mode`: fixed (`S_IFREG | 0644` for files, `S_IFDIR | 0755` for directories)
- `st_mtime`, `st_atime`, `st_ctime`: not meaningful (zero or backend-provided if available)
- `st_uid`, `st_gid`: fixed (current user)

### No file locking

Concurrent writes from multiple actor replicas to the same key are last-write-wins. This is inherent to KV/object stores. Actors are designed to be single-threaded per message, so this is only relevant for multi-replica actors writing to the same key — which is the fan-in case, handled by CAS (see [ADR-9](#adr-9-fan-in-as-crew-actor-using-state-mounts)).

### No seek on reads (object stores)

For object store backends (S3, GCS), `seek()` on read files is not supported — objects are streamed sequentially. For KV backends (Redis, NATS), the full value is fetched into a `BytesIO`, so seek works.

If seek is needed on S3 objects, the handler should read into a local buffer:

```python
import io

with open("./s3data/model.bin", "rb") as f:
    buf = io.BytesIO(f.read())  # fetch once, seek freely
    buf.seek(1024)
    header = buf.read(256)
```

### C extensions that bypass Python file I/O

The Python-level patching catches all code that goes through `builtins.open` — which includes `pathlib`, `io.open`, and any library that accepts file objects. The following table documents library compatibility:

| Library | Common operations | Uses Python `open()`? | Status |
|---------|------------------|----------------------|--------|
| `json` | `json.load(f)`, `json.dump(obj, f)` | yes (accepts file objects) | **works** |
| `pickle` | `pickle.load(f)`, `pickle.dump(obj, f)` | yes (accepts file objects) | **works** |
| `numpy` | `np.load()`, `np.save()` | yes | **works** |
| `numpy` | `np.fromfile()` | no (C `fread`) | **gap** — use `np.frombuffer(f.read())` instead |
| `numpy` | `np.memmap()` | no (C `mmap`) | **gap** — incompatible with remote storage by design |
| `torch` | `torch.save()`, `torch.load()` | yes (Python `open` + pickle) | **works** |
| `torch` | `torch.jit.load()` | no (C++) | **gap** — load into `BytesIO` first: `torch.jit.load(io.BytesIO(f.read()))` |
| PIL/Pillow | `Image.open(path)` | yes (Python `open`) | **works** |
| OpenCV | `cv2.imread()`, `cv2.imwrite()` | no (C++) | **gap** — use: `cv2.imdecode(np.frombuffer(f.read(), np.uint8), ...)` |
| pandas | `pd.read_csv()`, `pd.read_json()` | yes | **works** |
| pandas | `pd.read_parquet()` | no (pyarrow C++) | **gap** — pass file object: `pd.read_parquet(f)` |
| HuggingFace | `from_pretrained()`, `save_pretrained()` | yes (Python `open` + `torch.save`) | **works** |
| TensorFlow | `tf.io.read_file()`, `model.save()` | no (C++) | **gap** — TF has native `tf.io.gfile` with S3/GCS support; use that directly |

**Workaround pattern for all gaps**: Read into a file object first, then pass the file object (not the path) to the library.

```python
# General workaround: read state file into memory, pass to library
with open("./s3data/model.pt", "rb") as f:
    data = f.read()  # intercepted, streamed from S3

# Then use library with in-memory data
img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
arr = np.frombuffer(data, dtype=np.float32)
model = torch.jit.load(io.BytesIO(data))
df = pd.read_parquet(io.BytesIO(data))
```

This is documented behavior, not a bug. The Python-level interception is a deliberate design choice: it covers the vast majority of use cases without requiring elevated container privileges (FUSE/SYS_ADMIN), kernel modules, or LD_PRELOAD tricks.

---

## Local Development

When `ASYA_STATE_MOUNTS` is unset (local development, testing), no patching occurs. Mount paths resolve to real directories on disk:

```python
# This code works identically in both environments:
with open("./cache/user/123", "w") as f:
    json.dump(context, f)

# Local: writes to ./cache/user/123 on disk
# Deployed: intercepted, PUT to connector -> Redis
```

No conditional imports, no environment detection, no mock objects. The same handler code runs locally and in production.

---

## Examples

### Agentic per-user context storage

```python
import json, os

async def handle(payload):
    user_id = payload["user_id"]
    context_path = f"./cache/context/{user_id}"

    # Load existing context (or start fresh)
    if os.path.exists(context_path):
        with open(context_path) as f:
            context = json.load(f)
    else:
        context = {"history": [], "preferences": {}}

    # Process message, update context
    context["history"].append(payload["message"])
    response = await call_llm(context)
    context["preferences"].update(response.get("learned_prefs", {}))

    # Save updated context
    with open(context_path, "w") as f:
        json.dump(context, f)

    return {"reply": response["text"]}
```

```yaml
spec:
  state:
    - backend: redis
      config:
        endpoint: redis://context-store:6379/0
      mount: ./cache
```

### Media file storage

```python
from PIL import Image
import io

async def handle(payload):
    # Read input image from object store
    with open(f"./s3data/uploads/{payload['image_id']}.jpg", "rb") as f:
        img = Image.open(f)

    # Process
    result = transform(img)

    # Write result back to object store
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    with open(f"./s3data/results/{payload['image_id']}.png", "wb") as f:
        f.write(buf.getvalue())

    return {"status": "processed", "output_key": f"results/{payload['image_id']}.png"}
```

```yaml
spec:
  state:
    - backend: s3
      config:
        bucket: media-pipeline
        prefix: v1/
        region: us-east-1
      mount: ./s3data
```

### Session files with multiple stores

```python
import json, os, pickle

async def handle(payload):
    session_id = payload["session_id"]

    # Fast KV for session metadata (Redis)
    meta_path = f"./cache/sessions/{session_id}"
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    else:
        meta = {"step": 0, "created": payload["timestamp"]}

    # Object store for large artifacts (S3)
    artifact_dir = f"./s3data/sessions/{session_id}"
    existing = os.listdir(artifact_dir) if os.path.isdir(artifact_dir) else []

    # Process
    result, artifact = await process_step(payload, meta, existing)

    # Write artifact to S3
    with open(f"{artifact_dir}/step-{meta['step']}.pkl", "wb") as f:
        pickle.dump(artifact, f)

    # Update session metadata in Redis
    meta["step"] += 1
    with open(meta_path, "w") as f:
        json.dump(meta, f)

    return result
```

```yaml
spec:
  stateProxy:
    - backend: redis
      config:
        endpoint: redis://sessions:6379/0
      mount: ./cache
    - backend: s3
      config:
        bucket: session-artifacts
        prefix: prod/
      mount: ./s3data
```

---

## Implementation Plan

### Phase 1: Protocol and connector framework

- Define HTTP-over-Unix-socket protocol (finalized above)
- Build connector base/framework (Go) with shared socket listener, health checks, graceful shutdown
- Implement `asya-connector-s3` (first backend)
- Implement `asya-connector-redis` (second backend)

### Phase 2: Runtime interception

- Add state hook installation to `asya_runtime.py` (~80-100 lines)
- Implement `_StateReadFile` and `_StateWriteFile` wrappers
- Implement Unix socket HTTP client
- Implement mount resolution and function patching
- Unit tests for interception layer

### Phase 3: Injector and XRD integration

- Add `stateProxy` field to AsyncActor XRD
- Update injector to add connector sidecars, socket volumes, and env vars
- Update Crossplane compositions

### Phase 4: Testing and documentation

- Component tests: runtime <-> connector over Unix socket
- Integration tests: full pipeline with state access
- Document C extension workarounds (table above)
- Document local development workflow

---

## Architecture Decision Records

### ADR-1: Transparent filesystem emulation vs. client library

**Context**: Actors need to access persistent state. Two approaches: (a) provide a client library (`from asya import kv; kv.get("key")`), or (b) intercept standard Python file I/O so handlers use `open()`, `os.path.exists()`, etc.

| Approach | UX | Local dev | Special imports | C extension support |
|----------|-----|-----------|----------------|-------------------|
| Client library | Explicit API | Needs mock or local adapter | Yes (`from asya import kv`) | N/A (explicit calls) |
| **FS emulation** | **Standard Python I/O** | **Works with real files, zero setup** | **None** | **Documented gaps with workarounds** |

**Decision**: Filesystem emulation.

**Rationale**: The strongest argument is local development parity. With FS emulation, the handler code `open("./cache/key", "w")` works identically on a developer's laptop (real files) and in production (intercepted, routed to Redis/S3). No mocks, no conditional imports, no environment detection. The handler author does not need to know Asya exists.

The documented gaps (C extensions that bypass Python's `open()`) are narrow, have standard workarounds (pass file objects instead of paths), and affect edge cases rather than the primary use cases.

### ADR-2: Python-level patching vs. FUSE vs. LD_PRELOAD vs. seccomp

**Context**: Multiple approaches exist for intercepting file operations.

| Approach | Coverage | Privileges | Complexity | K8s compatibility |
|----------|----------|-----------|------------|-------------------|
| **Python patching** | **builtins.open, os.*, pathlib** | **None** | **~100 lines** | **Any cluster** |
| FUSE | All operations (kernel-level) | SYS_ADMIN, /dev/fuse, mountPropagation: Bidirectional | ~1000 lines + kernel interaction | Requires privileged pods |
| LD_PRELOAD | All libc calls | None | ~400 lines C | Any cluster |
| seccomp_unotify | All syscalls | CAP_SYS_ADMIN or pre-installed profile | ~800 lines C | Requires security policy changes |

**Decision**: Python-level patching.

**Rationale**: The target workloads are Python actor handlers. For the documented use cases (JSON, pickle, torch, PIL, pandas CSV, HuggingFace), all operations go through `builtins.open`. The few gaps (OpenCV, numpy.fromfile, pyarrow internals) have simple workarounds. Python patching requires zero privileges, works in any Kubernetes cluster (including hardened multi-tenant clusters with PodSecurityStandards), and adds minimal code to the runtime.

FUSE provides complete coverage but requires privileged pods — unacceptable for multi-tenant production clusters. LD_PRELOAD is a reasonable middle ground but requires a compiled C shared library, adding build and maintenance complexity. seccomp_unotify requires security policy changes.

If a future use case requires complete syscall interception (e.g., Go-based actor runtimes), LD_PRELOAD or FUSE can be revisited for that specific runtime. The connector protocol is transport-agnostic — the same connectors work regardless of interception method.

### ADR-3: Connector sidecar vs. extending asya-sidecar

**Context**: Backend-specific state proxy logic (S3 SDK calls, Redis commands) must run somewhere. Two options: (a) extend `asya-sidecar` with state proxy endpoints, or (b) deploy separate connector sidecar containers.

| Approach | Modularity | Sidecar complexity | Independent versioning | User-extensible |
|----------|-----------|-------------------|----------------------|----------------|
| Extend asya-sidecar | Low (monolith) | High (message routing + state proxy + N backends) | No (coupled releases) | No |
| **Connector sidecars** | **High (one container per backend)** | **Unchanged** | **Yes** | **Yes (custom connectors)** |

**Decision**: Separate connector sidecars.

**Rationale**: `asya-sidecar` has a focused responsibility: message routing between queues and the runtime. Adding state proxy logic with pluggable backends (S3, GCS, Redis, NATS, DynamoDB) would significantly increase its complexity, binary size, dependency tree, and attack surface. Separate connectors keep each component focused and independently deployable. Users can build custom connectors for proprietary storage systems by implementing the HTTP-over-Unix-socket protocol.

### ADR-4: HTTP over Unix socket vs. custom protocol

**Context**: The runtime needs to communicate with connectors. Options: custom JSON-RPC protocol, gRPC, or HTTP over Unix socket.

**Decision**: HTTP over Unix socket.

**Rationale**: HTTP gives streaming for free (chunked transfer encoding), uses Python stdlib (`http.client`), and is universally understood. The RESTful interface (`GET /keys/{key}`, `PUT /keys/{key}`, `HEAD /keys/{key}`) maps naturally to KV/object store semantics. Any language can implement a connector with an HTTP server library. No custom serialization, no protobuf compilation, no RPC framework dependencies.

### ADR-5: Write-on-close vs. write-through

**Context**: When the handler calls `f.write(data)`, should the data be sent to the connector immediately (write-through) or buffered and sent on `f.close()` (write-on-close)?

**Decision**: Write-on-close.

**Rationale**: For KV and object store backends, the natural unit of storage is a complete value, not a byte stream. S3 PutObject requires knowing the content upfront (or using multipart upload). Redis SET stores a complete value. Buffering writes and flushing on close matches these semantics. The `SpooledTemporaryFile` buffer handles memory efficiently (in-memory up to 4MB, disk-spill for larger writes).

Write-through would be more durable (data persists before close) but requires streaming upload protocols on every backend, adds complexity to the file-like wrapper, and doesn't match how handlers typically use files (write all data, then close).

### ADR-6: Stateless Deployment + external state vs. StatefulSet + local state

**Context**: Actors that need cross-message state could either maintain state locally (StatefulSet with per-pod storage) or externalize state to a shared database.

| Approach | Scaling | Complexity | Access latency | Failure mode |
|----------|---------|------------|----------------|--------------|
| StatefulSet + local RocksDB | Complex (shard rebalancing, placement directory, N per-pod queues) | High (sidecar changes, injector changes, XRD changes, new composition logic) | Sub-ms (local disk) | Pod failure = state locked on PVC until pod restarts |
| **Deployment + external state** | **Standard KEDA (no rebalancing)** | **Low (no framework changes)** | **~1ms (Redis), ~5ms (S3)** | **Pod failure = message returns to queue, another pod continues** |

**Decision**: Stateless Deployment with external state store.

**Rationale**: For Asya's primary workload (AI pipelines), each actor takes seconds to process a message. The ~1-5ms overhead of an external state store is negligible compared to seconds of LLM inference. The architectural simplicity is worth far more than sub-millisecond local access:

- No shard routing or placement logic
- No StatefulSet controller interactions
- Standard KEDA autoscaling
- Graceful failure handling (message returns to queue, any pod retries)

**Consequence**: Actors that genuinely need local disk state (e.g., high-throughput streaming with sub-ms latency requirements) cannot use this pattern. Such workloads are out of scope for Asya's actor model.

### ADR-7: Against shard affinity for fan-in

**Context**: The original design used shard affinity (StatefulSet with per-pod queues) so that all partial results for a given key would land on the same pod. This required a placement directory to map keys to shards.

Multiple shard routing approaches were explored:

| Approach | How it works | Problem |
|----------|-------------|---------|
| Static hashing (rendezvous / consistent hash) | Sender computes `hash(key) % N` | Scale events remap keys — partial results split across old and new shards |
| Stamped-N | Gateway stamps shard count into message | Gateway must know N reliably; ConfigMap sync lag makes this unreliable |
| Virtual shards | `hash(key) % V`, V mapped to N | Scale events require reassigning virtual shards and migrating state |
| Semi-stateful router | Placement directory in embedded KV | Router is SPOF; HA requires Raft consensus |

All shard affinity approaches suffer from the same fundamental problem: scale events require coordinated state migration or routing reconfiguration.

**Decision**: No shard affinity. Use external state store with CAS concurrency instead.

**Rationale**: The external state store eliminates the routing problem entirely. Any pod can process any message. Scale events require no coordination.

### ADR-8: Against building a placement directory

**Context**: To make shard affinity work with dynamic scaling, we explored building a placement directory. This is the pattern used by Dapr (Placement Service), Vitess (Lookup VIndex), and Akka (Shard Coordinator).

Multiple placement store options were evaluated:

| Store | Consistency | Verdict |
|-------|-------------|---------|
| Embedded Badger (single-node) | CP (single writer) | SPOF |
| Embedded Badger + hashicorp/raft | CP (Raft) | ~300-500 LoC of custom consensus code |
| NATS JetStream KV | CP (Raft) | Raft-limited throughput |
| Redis/Valkey | AP (async replication) | AP semantics break placement correctness |
| etcd | CP (Raft) | Overkill for routing table |

**Decision**: Do not build a placement directory. The external state store approach eliminates the need for one.

### ADR-9: Fan-in as crew actor using state mounts

**Context**: Fan-in aggregation requires cross-message state (partial results from fan-out converge). This was originally proposed as a separate `StateStore` interface in the crew actor. With the filesystem emulation approach, fan-in can use state mounts instead.

**Decision**: Fan-in crew actor (`x-fanin`) uses state mounts with CAS-capable backends.

**Rationale**: The state mount provides the storage interface. The fan-in handler reads/writes partial aggregation state through `open()` and `os.path.exists()` like any other actor. CAS semantics (needed for concurrent fan-in from multiple pods) are handled at the connector level — the connector exposes CAS via conditional headers:

```
PUT /keys/{key}
If-Match: {revision}    -> 200 (updated) or 409 (conflict, retry)

GET /keys/{key}
-> 200 + ETag: {revision}  (used for subsequent conditional PUT)
```

This keeps the runtime simple (no CAS awareness) and pushes concurrency control to the connector, where it belongs.

The fan-in protocol (message format, completeness detection, merge strategy) remains defined in a separate RFC.

### ADR-10: Use cases routed to appropriate layers

**Context**: Multiple stateful use cases were analyzed. Most do not belong in the actor layer.

| Use case | Layer | Rationale |
|----------|-------|-----------|
| **Agentic context storage** | **State mounts (this design)** | Bounded state per user, natural fit for KV/object store |
| **Media file storage** | **State mounts (this design)** | Object store is the natural backend |
| **Fan-in aggregation** | **State mounts + crew actor** | Bounded state, bounded lifetime, CAS for concurrency |
| **Session files** | **State mounts (this design)** | Intermediate artifacts, bounded per session |
| Deduplication | Gateway | Gateway already tracks task state |
| Per-key rate limiting | Gateway | Rate limiting is an ingress concern |
| Time-window batching | Out of scope | Stream processing semantics (Flink territory) |

**Decision**: State mounts serve the four actor-layer use cases. Gateway concerns and stream processing remain out of scope.

---

## Open Questions

1. **Connector health checks**: How does the runtime know if a connector is ready before the handler starts? Options: readiness probe on the connector socket, or the runtime retries connection on first state access.

2. **State store lifecycle**: Who provisions the backend (Redis, S3 bucket, etc.)? Options: user-managed (BYO), Crossplane-managed (auto-provision with the actor), or Helm-chart-managed.

3. **TTL and cleanup**: For KV backends (Redis, NATS), should keys have automatic TTL? Configurable per mount? This prevents unbounded growth from orphaned state.

4. **CAS protocol details**: The conditional PUT (`If-Match` / `ETag`) protocol for fan-in needs formal specification. Should the runtime expose CAS semantics to handlers, or keep it hidden in the connector?

5. **Mount path conventions**: Should mount paths be relative to workdir (`./cache/`) or absolute (`/asya/state/cache/`)? Relative is more natural for handlers, absolute is more predictable for the interception layer.

6. **Binary vs. text mode**: Should `open(path, "r")` (text mode) perform encoding/decoding, or should the connector always return raw bytes? Text mode with UTF-8 is the expected default for most use cases.

---

## Rejected Alternative: StatefulSet-Based Approach

The original design proposed StatefulSets with per-pod queues and shard affinity. See ADRs 6-8 for the detailed analysis and rejection rationale. The core issues:

- Scale events require coordinated state migration
- Placement directories add distributed consensus complexity
- StatefulSets break standard KEDA autoscaling
- Pod failure locks state on PVC until restart

The stateless Deployment + external state approach eliminates all of these problems with negligible latency overhead for AI workloads.

---

## References

- Fan-In Protocol RFC (TBD) — Message format, completeness detection, merge strategy
- Resiliency RFC (#181) — Sidecar retry logic with exponential backoff
- Actor Flavors RFC — composable presets including state backends
