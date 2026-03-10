# State Proxy

## Overview

The state proxy gives actors persistent state access via standard Python file
operations (`open`, `os.stat`, `os.listdir`, `os.remove`). Handlers read and
write state as if it were a local directory — no SDK, no special imports.

The runtime patches Python builtins at startup to intercept file operations on
configured mount paths and translates them to HTTP requests over Unix sockets to
connector sidecar processes. Each connector adapts those HTTP requests to a
specific storage backend (S3, Redis).

## Architecture

```
Handler code (actor runtime)
  open("/state/model.bin", "rb")
          │
          ▼
  patched builtins.open
  (installed by _install_state_proxy_hooks)
          │
          ▼
  HTTP GET /keys/model.bin
  over Unix socket: /var/run/asya/state/{name}.sock
          │
          ▼
  Connector sidecar (e.g. s3-buffered-lww)
          │
          ▼
  Storage backend (S3, Redis)
```

### Pod layout

When `stateProxy` is configured, the Crossplane composition adds one connector container per
mount to the actor pod. All connector containers share the `state-sockets`
emptyDir volume with the runtime container.

```
Pod
├── asya-runtime          (runtime + user handler)
│   ├── /var/run/asya/state/      ← state-sockets volume
│   └── /state/meta/              ← logical mount path (no real FS)
│
├── asya-state-proxy-meta  (connector sidecar)
│   ├── /var/run/asya/state/meta.sock  ← Unix socket
│   └── env: CONNECTOR_SOCKET, STATE_BUCKET, ...
│
└── asya-state-proxy-media (another mount, if configured)
    └── /var/run/asya/state/media.sock
```

## Configuration

### AsyncActor CRD

Configure state proxy in `spec.stateProxy`:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: model-inference
  namespace: prod
spec:
  actor: model-inference
  transport: sqs

  stateProxy:
    - name: weights          # DNS label, becomes socket name: weights.sock
      mount:
        path: /state/weights # Absolute path intercepted in runtime container
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

    - name: cache
      mount:
        path: /state/cache
      writeMode: passthrough
      connector:
        image: ghcr.io/deliveryhero/asya-state-proxy-s3-passthrough:v1.0.0
        env:
          - name: STATE_BUCKET
            value: my-inference-cache
```

### XRD fields

Defined in `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml`:

| Field | Type | Description |
|-------|------|-------------|
| `stateProxy[].name` | string | Unique mount identifier (DNS label, 1-63 chars) |
| `stateProxy[].mount.path` | string | Absolute path in runtime container |
| `stateProxy[].writeMode` | enum | `buffered` (default) or `passthrough` |
| `stateProxy[].connector.image` | string | Connector container image |
| `stateProxy[].connector.env` | array | Backend-specific environment variables |
| `stateProxy[].connector.resources` | object | Kubernetes resource requests/limits |

## Crossplane Composition Step

When the Crossplane composition processes an AsyncActor with `stateProxy` entries, it:

1. Adds a `state-sockets` emptyDir volume to the pod.
2. For each mount entry, adds a connector container:
   - Name: `asya-state-proxy-{name}`
   - Env: `CONNECTOR_SOCKET=/var/run/asya/state/{name}.sock` plus any
     `connector.env` values from the spec
   - VolumeMount: `state-sockets` at `/var/run/asya/state`
3. On the `asya-runtime` container:
   - Mounts `state-sockets` at `/var/run/asya/state`
   - Sets `ASYA_STATE_PROXY_MOUNTS` env var

The `ASYA_STATE_PROXY_MOUNTS` format is semicolon-separated entries:

```
{name}:{mountPath}:write={writeMode}[;{name}:{mountPath}:write={writeMode}]*
```

Example:

```
weights:/state/weights:write=buffered;cache:/state/cache:write=passthrough
```

## Runtime Hooks

Source: `src/asya-runtime/asya_runtime.py`, function `_install_state_proxy_hooks`

When `ASYA_STATE_PROXY_MOUNTS` is set, the runtime installs hooks before the
handler initialises:

```python
builtins.open  →  _patched_open
os.stat        →  _patched_stat
os.listdir     →  _patched_listdir
os.unlink      →  _patched_unlink
os.remove      →  _patched_unlink   (alias)
os.makedirs    →  _patched_makedirs (no-op for mount paths)
```

Calls to non-mount paths are forwarded to the original functions unchanged.

### Mount resolution

`_resolve_mount` normalises the path and checks whether it starts with a
configured mount prefix. If it matches, the key (path relative to mount) and the
mount's socket path are returned.

### Handler usage

```python
# Read state (no imports needed)
with open("/state/weights/model.bin", "rb") as f:
    weights = f.read()

# Write state
with open("/state/cache/result.json", "w") as f:
    f.write(json.dumps(result))

# Check existence
import os
if os.path.exists("/state/cache/result.json"):
    ...

# List directory
files = os.listdir("/state/weights/")

# Delete
os.remove("/state/cache/stale.json")
```

## Limitations and Compatibility

The state proxy works by patching Python builtins at the interpreter level. This
means it intercepts **Python-level** file operations but cannot intercept
**C-level** system calls made by native extensions.

### What is patched

| Python API | Patched | Notes |
|------------|---------|-------|
| `builtins.open()` | ✅ | Primary file I/O — most libraries use this |
| `os.stat()` | ✅ | Returns synthetic `stat_result` (see below) |
| `os.path.exists()` | ✅ | Works via patched `os.stat()` internally |
| `os.path.isfile()` / `os.path.isdir()` | ✅ | Works via patched `os.stat()` internally |
| `os.path.getsize()` | ✅ | Works via patched `os.stat()` internally |
| `os.listdir()` | ✅ | Lists keys from connector |
| `os.remove()` / `os.unlink()` | ✅ | Deletes key via connector |
| `os.makedirs()` | ✅ | No-op for mount paths (flat key-value store) |

### What is NOT patched

| Python API | Patched | Workaround |
|------------|---------|------------|
| `os.open()` | ❌ | Use `builtins.open()` instead |
| `os.rename()` / `os.replace()` | ❌ | Read + write + delete manually |
| `os.scandir()` | ❌ | Use `os.listdir()` |
| `os.walk()` | ❌ | Use `os.listdir()` recursively |
| `os.chmod()` / `os.chown()` | ❌ | Not applicable (no real filesystem) |
| `mmap.mmap()` | ❌ | Read into `io.BytesIO` instead |
| `pathlib.Path.open()` | ❌ | Calls `io.open()` internally, not `builtins.open()` |
| `pathlib.Path.read_bytes()` | ❌ | Use `open(path, "rb")` instead |
| `shutil.copy2()` | ❌ | Fails copying filesystem metadata |

### Filesystem metadata

`os.stat()` returns a synthetic `os.stat_result` with limited fields:

| Field | Value | Real? |
|-------|-------|-------|
| `st_size` | Actual content size | ✅ |
| `st_mode` | `0o644` (file) / `0o755` (dir) | ❌ Synthetic |
| `st_uid` / `st_gid` | Current process user | ❌ Synthetic |
| `st_ino` | `0` | ❌ Not available |
| `st_dev` | `0` | ❌ Not available |
| `st_nlink` | `1` | ❌ Always 1 |
| `st_atime` / `st_mtime` / `st_ctime` | `0` | ❌ Not available |

Libraries that depend on modification times (e.g. caching based on `mtime`) will
not work correctly.

### Libraries that work

Any pure-Python library that reads or writes via `builtins.open()` works
transparently:

```python
import json, csv, pickle, configparser

# json — uses open() internally
with open("/state/meta/config.json") as f:
    config = json.load(f)

# csv — wraps a file object from open()
with open("/state/meta/data.csv") as f:
    reader = csv.reader(f)
    rows = list(reader)

# pickle — uses open() in binary mode
with open("/state/meta/model.pkl", "rb") as f:
    model = pickle.load(f)

# yaml (PyYAML) — wraps a file object from open()
import yaml
with open("/state/meta/spec.yaml") as f:
    spec = yaml.safe_load(f)

# PIL/Pillow — pass a file object (not a path string)
from PIL import Image
with open("/state/meta/photo.png", "rb") as f:
    img = Image.open(f)
    img.load()  # Force read before file closes
```

### Libraries that do NOT work (with path strings)

Libraries with C extensions that perform their own system-level I/O bypass the
Python-level patch:

```python
# These will FAIL — they use C-level file I/O, not builtins.open()
import pandas as pd
df = pd.read_parquet("/state/meta/data.parquet")    # pyarrow C extension
df = pd.read_csv("/state/meta/data.csv")            # C parser by default

import torch
model = torch.load("/state/meta/model.pt")          # C extension

import numpy as np
arr = np.load("/state/meta/array.npy")              # C extension

import h5py
f = h5py.File("/state/meta/data.h5")                # HDF5 C library

import cv2
img = cv2.imread("/state/meta/photo.png")           # OpenCV C library
```

### Workaround: read into BytesIO

Read the data through `open()` first, then pass an `io.BytesIO` buffer to the
library:

```python
import io

# pandas
with open("/state/meta/data.parquet", "rb") as f:
    df = pd.read_parquet(io.BytesIO(f.read()))

# pandas CSV (force Python parser, or use BytesIO)
with open("/state/meta/data.csv", "rb") as f:
    df = pd.read_csv(io.BytesIO(f.read()))

# torch
with open("/state/meta/model.pt", "rb") as f:
    model = torch.load(io.BytesIO(f.read()))

# numpy
with open("/state/meta/array.npy", "rb") as f:
    arr = np.load(io.BytesIO(f.read()))

# Pillow (already works with file objects)
with open("/state/meta/photo.png", "rb") as f:
    img = Image.open(io.BytesIO(f.read()))
```

For writes, buffer first and write through `open()`:

```python
# pandas to parquet
buf = io.BytesIO()
df.to_parquet(buf)
with open("/state/meta/data.parquet", "wb") as f:
    f.write(buf.getvalue())

# torch save
buf = io.BytesIO()
torch.save(model.state_dict(), buf)
with open("/state/meta/model.pt", "wb") as f:
    f.write(buf.getvalue())
```

### Directory semantics

The state proxy is a flat key-value store, not a real filesystem. Paths like
`/state/meta/subdir/file.txt` are stored as the key `subdir/file.txt` — there is
no actual `subdir/` directory. `os.makedirs()` is a no-op for mount paths.
`os.listdir()` uses the connector's prefix-based listing to simulate directory
entries.

## HTTP Protocol

Source: `src/asya-state-proxy/asya_state_proxy/server.py`

Each connector runs `ConnectorServer` on a Unix socket. The runtime connects
via `_UnixHTTPClient` (a subclass of `http.client.HTTPConnection`).

**Socket path**: `/var/run/asya/state/{name}.sock`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/keys/{key}` | Read key, returns body bytes |
| `PUT` | `/keys/{key}` | Write key, body is the data |
| `HEAD` | `/keys/{key}` | Stat key, returns `Content-Length` and `X-Is-File` headers |
| `DELETE` | `/keys/{key}` | Delete key |
| `GET` | `/keys/?prefix=X&delimiter=Y` | List keys under prefix |
| `GET` | `/healthz` | Liveness check, returns `{"status": "ready"}` |

List response body:

```json
{"keys": ["file.txt", "other.bin"], "prefixes": ["subdir/"]}
```

## Write Modes

Write mode controls how the runtime buffers data before sending it to the connector.

### buffered

`_BufferedWriteFile` collects all writes into a `SpooledTemporaryFile`
(spills to disk above 4 MiB). On `close()`, it sends a single `PUT` with
`Content-Length`.

- Supports `seek()` and `tell()` before close
- Suitable for small-to-medium files where the full size is needed upfront
- Default for all connectors except passthrough

### passthrough

`_PassthroughWriteFile` opens the HTTP connection immediately, sends each
`write()` call as an HTTP chunk using chunked transfer encoding, and finalises on
`close()`.

- Does not buffer in memory — suitable for large files
- Does not support `seek()` or `tell()`
- Used when `writeMode: passthrough` is set in the AsyncActor spec

## Connector Types

Source: `src/asya-state-proxy/asya_state_proxy/connectors/`

All connectors implement the `StateProxyConnector` abstract base class
(`src/asya-state-proxy/asya_state_proxy/interface.py`):

```python
class StateProxyConnector(ABC):
    def read(self, key: str) -> BinaryIO: ...
    def write(self, key: str, data: BinaryIO, size: int | None = None) -> None: ...
    def exists(self, key: str) -> bool: ...
    def stat(self, key: str) -> KeyMeta | None: ...
    def list(self, key_prefix: str, delimiter: str = "/") -> ListResult: ...
    def delete(self, key: str) -> None: ...
```

### s3-buffered-lww

Image suffix: `s3-buffered-lww`

Last-Write-Wins semantics. Writes always overwrite the existing object. No
conflict detection. Suitable for state that is written by a single actor instance.

Required env: `STATE_BUCKET`. Optional: `STATE_PREFIX`, `AWS_REGION`,
`AWS_ENDPOINT_URL`.

### s3-passthrough

Image suffix: `s3-passthrough`

Streaming writes directly to S3 via `upload_fileobj`. Reads return a
`StreamingBody` wrapper without buffering. No conflict detection.

Required env: `STATE_BUCKET`. Optional: `STATE_PREFIX`, `AWS_REGION`,
`AWS_ENDPOINT_URL`.

### s3-buffered-cas

Image suffix: `s3-buffered-cas`

Check-And-Set with ETag-based conflict detection. On read, the ETag is cached
in memory. On write, a conditional `PutObject` with `IfMatch: {cached_etag}` is
sent. If the object was modified externally since the last read, S3 returns
`PreconditionFailed`, which the connector maps to `FileExistsError`.

Write is unconditional for keys that have never been read (new key path).

Required env: `STATE_BUCKET`. Optional: `STATE_PREFIX`, `AWS_REGION`,
`AWS_ENDPOINT_URL`.

### redis-buffered-cas

Image suffix: `redis-buffered-cas`

Check-And-Set with Redis WATCH/MULTI/EXEC optimistic locking. On write, the key
is watched; if it changes before the transaction executes, `WatchError` is raised
and mapped to `FileExistsError`.

Required env: `REDIS_URL` (e.g. `redis://localhost:6379/0`). Optional:
`STATE_PREFIX`.

## Error Mapping

Source: `src/asya-runtime/asya_runtime.py`, `_raise_for_status`

HTTP error responses from the connector are mapped to standard Python exceptions:

| HTTP status | Python exception |
|-------------|-----------------|
| 400 | `ValueError` |
| 403 | `PermissionError` |
| 404 | `FileNotFoundError` |
| 409 | `FileExistsError` (CAS conflict) |
| 413 | `OSError(errno.EFBIG, ...)` |
| 500 | `OSError` |
| 503 | `ConnectionError` |
| 504 | `TimeoutError` |

Handler code can catch these exceptions directly:

```python
try:
    with open("/state/cache/result.json", "rb") as f:
        cached = json.load(f)
except FileNotFoundError:
    cached = None  # Cache miss
```

## Connector Environment Variables

| Variable | Connectors | Description |
|----------|-----------|-------------|
| `CONNECTOR_SOCKET` | all | Unix socket path (set by Crossplane composition) |
| `STATE_BUCKET` | s3-* | S3 bucket name |
| `STATE_PREFIX` | s3-*, redis | Key prefix within bucket or namespace |
| `AWS_REGION` | s3-* | AWS region (default: `us-east-1`) |
| `AWS_ENDPOINT_URL` | s3-* | Custom endpoint for MinIO/LocalStack |
| `REDIS_URL` | redis-* | Redis connection URL |

## Related Components

- [Crossplane Compositions](asya-crossplane.md) — reads `stateProxy` from AsyncActor XR and renders connector containers
- [Runtime](asya-runtime.md) — installs file I/O hooks from `ASYA_STATE_PROXY_MOUNTS`
- XRD definition: `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml`
- Connector server: `src/asya-state-proxy/asya_state_proxy/server.py`
- Connector interface: `src/asya-state-proxy/asya_state_proxy/interface.py`
