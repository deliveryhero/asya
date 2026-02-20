---
title: Stateful Actors — Transparent State Access
status: open
priority: 2 # medium
type: epic
---

# Design doc


## Summary

Asya actors access persistent state through **transparent filesystem emulation (limited operations)**. Actors read and write files under designated mount paths (e.g., `/state/cache/`, `/state/media/`), and `asya_runtime.py` intercepts these operations, translating them to HTTP requests over Unix socket against a **state proxy sidecar** that implements the actual storage backend (S3, GCS, Redis, NATS KV, etc.).

All actors remain **stateless Deployments** — there are no StatefulSets, no per-pod storage, no shard affinity. The state is always external, accessed through a uniform filesystem interface.

The runtime is a **dumb translator** — it intercepts Python file I/O and forwards operations to the proxy. The **proxy is smart** — it decides buffering strategy, atomicity guarantees, CAS behavior, and retries. Adding new guarantee types means building a new proxy connector, not modifying the runtime.

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
- **Modular backends**: Each storage backend is a separate state proxy sidecar — no backend logic in `asya_runtime.py` or `asya-sidecar`
- **Streaming support**: Large files (media, model weights) are streamed, not buffered entirely in memory
- **No framework bloat**: `asya_runtime.py` remains a single file with zero dependencies
- **Exception parity**: The same `try/except FileNotFoundError` works with real files (local) and proxied files (production)

---

## Use Cases

| Use Case | Value Size | Access Pattern | Consistency | Concurrency Model |
|----------|-----------|---------------|-------------|-------------------|
| **Fan-in metadata** (partial aggregation counters) | tiny (<10KB) | random key r/w | strong + CAS | multiple writers to same key |
| **A/B test config** | tiny (<10KB) | read-heavy | strong reads | single writer, many readers |
| **Agentic long-term memory** | small-medium (<1MB) | random key r/w | strong | one user = one writer (partitioned) |
| **Short memory offloading** | small-medium (<1MB) | write-heavy, periodic reads | strong | one user = one writer |
| **Media blobs** (images, audio) | medium (1-100MB) | write-once, read-many | eventual OK | no conflicts (UUID keys) |
| **Huge files** (video, datasets) | large (100MB-GBs) | streaming sequential | eventual OK | no conflicts (UUID keys) |

---

## Architecture

```
User container                          State proxy sidecar(s)
+-------------------------------+
| Handler code                  |
|   open("/state/media/k", "w") |
|   os.path.exists("/state/m/k")|
+-----------+-------------------+
            |
            v
+-----------+-------------------+
| asya_runtime.py               |
|   - patches builtins.open,    |    Unix socket          +----------------------------+
|     os.stat, os.listdir,      |---(/var/run/asya/state/--| asya-state-proxy-media     |---> S3
|     os.scandir, os.unlink     |    media.sock)           | (s3-buffered-cas connector)|
|   - translates path ops to    |                          +----------------------------+
|     HTTP over Unix socket     |    Unix socket          +----------------------------+
|   - dumb translator           |---(/var/run/asya/state/--| asya-state-proxy-meta      |---> Redis
|     (~80 lines, zero config)  |    meta.sock)            | (redis-buffered-cas)       |
+-------------------------------+                          +----------------------------+

+-------------------------------+
| asya-sidecar (Go)             |   (unchanged — message routing only)
+-------------------------------+
```

### Component responsibilities

| Component | Responsibility |
|-----------|---------------|
| `asya_runtime.py` | Patches Python file I/O for configured mount paths; translates operations to HTTP requests over Unix socket. Dumb translator — ~80 lines added, zero new dependencies, zero configuration beyond mount paths. |
| State proxy connectors | Separate container image per backend+guarantees combination (e.g., `s3-buffered-cas`, `s3-passthrough`, `redis-buffered-cas`). Implements the `StateProxyConnector` interface over HTTP-over-Unix-socket. Owns all backend-specific logic, SDKs, credentials, CAS, and retry behavior. |
| `asya-sidecar` | Unchanged. Message routing only. |
| `asya-injector` | Adds state proxy sidecar containers and Unix socket volumes based on the actor's `stateProxy` spec. |
| Crossplane XRD | New optional `stateProxy` field defining mount configurations. |

### Container naming

State proxy containers follow a two-token prefix pattern consistent with other asya containers:

```
asya-runtime             (user handler)
asya-sidecar             (message routing)
asya-state-proxy-media   (state proxy for media mount)
asya-state-proxy-meta    (state proxy for meta mount)
```

The container name is derived from the `stateProxy[].name` field: `asya-state-proxy-{name}`.

### Why separate state proxy sidecars?

- **Modularity**: Each connector is a focused, single-purpose container. Adding a new backend means building a new image, not modifying the sidecar.
- **Independent lifecycle**: Connectors can be versioned and updated independently of the sidecar and runtime.
- **Credential isolation**: Each connector manages its own credentials (IAM roles, Redis auth, etc.) without exposing them to the runtime or sidecar.
- **User-extensible**: Platform teams can build custom connectors implementing the same interface for proprietary storage systems. Connectors are named by the team (e.g., `s3-buffered-cas`, `s3-buffered-cas-cold`, `redis-buffered-lww`) — naming is up to the implementing team.

---

## Connector Guarantees Vocabulary

Instead of hard-coding categories, Asya defines a **vocabulary of guarantees** that connector implementations declare. Platform teams choose which guarantees their connector provides and name it accordingly.

### Guarantee dimensions

| Dimension | Values | Impact on Python interface |
|-----------|--------|---------------------------|
| **Buffering** | `buffered` / `passthrough` | `buffered`: seekable, text mode works, `SpooledTemporaryFile`. `passthrough`: not seekable, binary only, direct streaming. |
| **Write atomicity** | `atomic` / `non-atomic` | `atomic`: crash mid-write stores nothing (REQUIRED for `buffered`). `non-atomic`: partial data may exist after crash. |
| **Serialization** | `cas` / `last-write-wins` | `cas`: connector handles `ETag`/`If-Match` internally with retries. `last-write-wins`: no concurrency control. |

**Future dimensions** (not in v1, but the vocabulary is extensible):
- **Latency class**: `hot` / `warm` / `cold` — SLA expectations
- **Durability**: `durable` / `ephemeral` — survives restarts or not
- **TTL support**: `ttl` / `no-ttl` — automatic key expiration

### Constraints between guarantees

| Rule | Rationale |
|------|-----------|
| `buffered` implies `atomic` | If the connector buffers the full value, it MUST provide atomic writes. The connector receives the full body before writing — enforced at the protocol level. |
| `passthrough` implies `non-atomic` | Streaming data means partial writes are possible. Connectors cannot guarantee atomicity for streaming uploads. |
| `cas` requires `buffered` | CAS requires reading the full value (to get revision) and writing the full value (with If-Match). Doesn't work with streaming. |

### Valid combinations

| Buffering | Atomicity | Serialization | Example connector name |
|-----------|-----------|---------------|------------------------|
| `buffered` | `atomic` | `cas` | `s3-buffered-cas`, `redis-buffered-cas`, `nats-kv-buffered-cas` |
| `buffered` | `atomic` | `last-write-wins` | `s3-buffered-lww`, `redis-buffered-lww` |
| `passthrough` | `non-atomic` | `last-write-wins` | `s3-passthrough`, `gcs-passthrough` |

### How the runtime uses guarantees

The runtime needs exactly **one** piece of information per mount: the **write buffering mode** (`write=buffered` or `write=passthrough`). This is provided via the single `ASYA_STATE_PROXY_MOUNTS` environment variable (see [Configuration](#configuration)).

For reads, the runtime auto-detects behavior from the proxy's HTTP response format:
- Response has `Content-Length` header: runtime buffers into `SpooledTemporaryFile` (seekable)
- Response uses `Transfer-Encoding: chunked`: runtime wraps response directly (not seekable, streaming)

---

## Connector Interface

One Python interface. All connectors implement all 6 methods. The difference between `buffered` and `passthrough` is in **how** they implement `read()` and `write()`, not **which** methods they implement.

```python
from abc import ABC, abstractmethod
from typing import BinaryIO, Optional, NamedTuple


class KeyMeta(NamedTuple):
    size: int
    is_file: bool


class ListResult(NamedTuple):
    keys: list[str]        # file entries (immediate children)
    prefixes: list[str]    # directory entries (common prefixes)


class StateProxyConnector(ABC):
    """State proxy connector interface.

    Maps 1-1 to Python file I/O intercepted by asya_runtime.py.
    One interface — buffered and passthrough connectors both implement
    all methods, differing only in HOW they handle read/write.

    Runtime translates Python operations:
        open(path, "rb") + f.read()       -> connector.read(key)
        open(path, "wb") + f.write/close  -> connector.write(key, data, size)
        os.path.exists(path)              -> connector.exists(key)
        os.stat(path)                     -> connector.stat(key)
        os.listdir(path)                  -> connector.list(prefix)
        os.remove(path)                   -> connector.delete(key)

    Runtime handles locally (NOT forwarded):
        f.seek(), f.tell()                -> SpooledTemporaryFile (buffered)
        f.readline(), f.readlines()       -> derived from read()
        text encoding/decoding            -> bytes <-> str
        os.makedirs()                     -> no-op (prefixes are virtual)
        path -> key resolution            -> strips mount prefix
    """

    @abstractmethod
    def read(self, key: str) -> BinaryIO:
        """Read a value for a key from the backend.

        Returns a readable binary stream.
        - Buffered connectors: return stream with known size
            (Content-Length set, runtime buffers into SpooledTemporaryFile -> seekable)
        - Passthrough connectors: return chunked stream
            (no Content-Length, runtime wraps directly -> not seekable)

        The runtime detects which case based on the response format.

        CAS connectors: internally store revision for subsequent write().

        Raises:
            FileNotFoundError: key does not exist (HTTP 404)
        """

    @abstractmethod
    def write(self, key: str, data: BinaryIO, size: Optional[int] = None) -> None:
        """Write a value for a key to the backend.

        data: readable binary stream containing the value
        size: total size if known (buffered mode), None for streaming

        - Buffered connectors: size is set, data contains full value.
            MUST write atomically (all-or-nothing).
        - Passthrough connectors: size may be None, data is a stream.
            Read chunks and upload incrementally.

        CAS connectors: use stored revision from last read() for conditional
        write. On conflict: retry internally (configurable), then raise on
        persistent failure.

        Raises:
            FileExistsError: CAS conflict after all internal retries (HTTP 409)
            OSError: backend error (HTTP 500)
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a key exists.

        Maps to: os.path.exists(path)
        Returns True/False. Does NOT raise on missing key.
        """

    @abstractmethod
    def stat(self, key: str) -> Optional[KeyMeta]:
        """Get key metadata. Returns None if not found.

        Maps to: os.stat(path)
        Returns: KeyMeta(size=bytes, is_file=True/False) or None
        Does NOT raise on missing key.
        """

    @abstractmethod
    def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
        """List keys under a prefix with delimiter grouping.

        Maps to: os.listdir(path), os.scandir(path)
        Returns: ListResult(keys=[...], prefixes=[...])
            keys = immediate file entries
            prefixes = immediate directory entries
        """

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a key.

        Maps to: os.remove(path), os.unlink(path)

        Raises:
            FileNotFoundError: key does not exist (HTTP 404)
        """
```

### Buffered vs. passthrough implementation example

Same interface, different behavior:

```python
# Buffered connector (e.g., s3-buffered-cas)
class S3BufferedCAS(StateProxyConnector):

    def read(self, key: str) -> BinaryIO:
        obj = self.s3.get_object(Bucket=self.bucket, Key=key)
        body = obj["Body"].read()          # fetch full value
        stream = io.BytesIO(body)
        stream.size = len(body)            # runtime detects Content-Length
        return stream

    def write(self, key: str, data: BinaryIO, size: Optional[int] = None) -> None:
        body = data.read()                 # read full value
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=body)  # atomic


# Passthrough connector (e.g., s3-passthrough)
class S3Passthrough(StateProxyConnector):

    def read(self, key: str) -> BinaryIO:
        obj = self.s3.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"]                 # return streaming body directly

    def write(self, key: str, data: BinaryIO, size: Optional[int] = None) -> None:
        # Multipart upload for streaming
        upload = self.s3.create_multipart_upload(Bucket=self.bucket, Key=key)
        parts = []
        part_num = 1
        while chunk := data.read(8 * 1024 * 1024):  # 8MB parts
            part = self.s3.upload_part(
                Bucket=self.bucket, Key=key,
                UploadId=upload["UploadId"],
                PartNumber=part_num, Body=chunk)
            parts.append({"PartNumber": part_num, "ETag": part["ETag"]})
            part_num += 1
        self.s3.complete_multipart_upload(
            Bucket=self.bucket, Key=key,
            UploadId=upload["UploadId"],
            MultipartUpload={"Parts": parts})
```

---

## Error Mapping: HTTP Status to Python Exceptions

The connector communicates via HTTP over Unix socket. The runtime maps HTTP status codes to Python's standard `OSError` subclasses, ensuring **exception parity** between local development (real files) and production (proxied files).

### Error mapping table

| HTTP Status | Error code | Python Exception | When raised | Retryable? |
|-------------|-----------|------------------|-------------|------------|
| **404** | `key_not_found` | `FileNotFoundError` | `read()`, `delete()` on non-existent key | No |
| **409** | `conflict` | `FileExistsError` | CAS conflict after all connector-internal retries exhausted | Yes (asya-level) |
| **400** | `bad_request` | `ValueError` | Malformed key, invalid parameters | No |
| **403** | `permission_denied` | `PermissionError` | Backend auth failure, read-only mount write attempt | No |
| **413** | `too_large` | `OSError` (EFBIG) | Value exceeds connector's size limit | No |
| **500** | `internal_error` | `OSError` | Backend error, unexpected connector failure | Yes (asya-level) |
| **503** | `unavailable` | `ConnectionError` | Connector not ready, backend unreachable | Yes (asya-level) |
| **504** | `timeout` | `TimeoutError` | Operation timed out | Yes (asya-level) |

### Special cases per method

| Method | HTTP 404 behavior | Rationale |
|--------|-------------------|-----------|
| `exists()` | Returns `False` (not an exception) | Matches `os.path.exists()` behavior |
| `stat()` | Returns `None` (not an exception) | Used for existence checks |
| `delete()` | Raises `FileNotFoundError` | Matches `os.remove()` behavior |
| `read()` | Raises `FileNotFoundError` | Matches `open()` behavior |

### Error response format

Connectors return structured JSON on error:

```
HTTP/1.1 409 Conflict
Content-Type: application/json

{
    "error": "conflict",
    "message": "CAS conflict on key 'counter' after 3 retries",
    "retryable": true
}
```

### Runtime error translation (~15 lines)

```python
_STATUS_TO_EXCEPTION = {
    404: FileNotFoundError,
    409: FileExistsError,
    400: ValueError,
    403: PermissionError,
    413: lambda msg: OSError(errno.EFBIG, msg),
    500: OSError,
    503: ConnectionError,
    504: TimeoutError,
}

def _raise_for_status(resp, key):
    if resp.status >= 400:
        body = json.loads(resp.read())
        exc_class = _STATUS_TO_EXCEPTION.get(resp.status, OSError)
        raise exc_class(f"State proxy error on '{key}': {body['message']}")
```

---

## Two-Layer Retry Strategy

CAS behavior and retries are hidden inside the connector's `read()`/`write()` methods. The handler code is identical whether using a CAS connector or a last-write-wins connector.

```
+-------------------------------------------------------+
|  Layer 1: Connector-internal (fast, immediate)        |
|                                                       |
|  CAS conflict -> re-read latest revision ->           |
|  re-attempt write with new revision                   |
|  Configurable: CAS_MAX_RETRIES, CAS_RETRY_DELAY_MS   |
|  Scope: transient conflicts (race on same key)        |
+---------------------+---------------------------------+
                      | still failing after N retries
                      v
+-------------------------------------------------------+
|  Layer 2: Asya-level (message requeue)                |
|                                                       |
|  Connector raises error -> runtime raises ->          |
|  sidecar nacks message -> back to queue ->            |
|  exponential backoff -> handler re-runs fresh         |
|  (fresh read() sees latest value)                     |
|  Configurable: spec.resiliency                        |
+-------------------------------------------------------+
```

Layer 1 handles the common case (two pods wrote simultaneously, one retry fixes it). Layer 2 handles the rare case (sustained contention) by re-running the handler from scratch — which means a fresh `read()` that sees the latest value. The handler author doesn't need to know CAS exists.

---

## Protocol: HTTP over Unix Socket

Each state proxy connector listens on a Unix socket at `/var/run/asya/state/{name}.sock` and implements a RESTful API mapping to the `StateProxyConnector` interface:

### Endpoints

| Interface method | HTTP request | Success response |
|-----------------|-------------|------------------|
| `read(key)` | `GET /keys/{key}` | 200 + body stream |
| `write(key, data, size)` | `PUT /keys/{key}` | 200 / 204 |
| `exists(key)` | `HEAD /keys/{key}` | 204 (exists) / 404 (not found) |
| `stat(key)` | `HEAD /keys/{key}` | 204 + `Content-Length`, `X-Is-File` headers |
| `list(prefix)` | `GET /keys/?prefix={p}&delimiter=/` | 200 + JSON `{keys: [], prefixes: []}` |
| `delete(key)` | `DELETE /keys/{key}` | 204 |

### Read response format (determines runtime buffering)

**Buffered connectors** return a response with `Content-Length`:
```
HTTP/1.1 200 OK
Content-Length: 12345
Content-Type: application/octet-stream

<full value body>
```
Runtime detects `Content-Length`, buffers into `SpooledTemporaryFile` (seekable).

**Passthrough connectors** return a chunked response:
```
HTTP/1.1 200 OK
Transfer-Encoding: chunked
Content-Type: application/octet-stream

<chunked body>
```
Runtime detects chunked encoding, wraps response directly (not seekable, streaming).

### Listing variants

```
GET /keys/?prefix={p}                        -> 200 + JSON array of keys
GET /keys/?prefix={p}&delimiter=/            -> 200 + JSON {keys: [], prefixes: []}
GET /keys/?prefix={p}&delimiter=/&limit={n}  -> 200 + limited listing
```

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
  stateProxy:
    - name: meta
      mount:
        path: /state/meta
        # mode: rw             # future: ro | rw
      connector:
        image: asya-bridges/state-proxy/redis-buffered-cas:latest
        env:
          - name: STATE_ENDPOINT
            value: "redis://context-store:6379/0"
          - name: CAS_MAX_RETRIES
            value: "3"
          - name: CAS_RETRY_DELAY_MS
            value: "50"
        resources:
          requests:
            memory: 64Mi
          limits:
            memory: 128Mi

    - name: media
      mount:
        path: /state/media
      connector:
        image: asya-bridges/state-proxy/s3-passthrough:latest
        env:
          - name: STATE_BUCKET
            value: "media-pipeline"
          - name: STATE_PREFIX
            value: "prod/"
          - name: AWS_REGION
            value: "us-east-1"

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

### XRD field definitions

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Unique mount identifier. Used for socket path (`{name}.sock`), container name (`asya-state-proxy-{name}`), and env var generation. Must be DNS-compatible. |
| `mount.path` | yes | Absolute path where the mount appears inside the runtime container. Must start with `/`. |
| `connector.image` | yes | Absolute container image reference for the connector (e.g., `asya-bridges/state-proxy/redis-buffered-cas:latest`, where `asya-bridges` - official images, `asya-bridges-community/state-proxy/...` - community-contributed images). No short-name resolution — always the full image. |
| `connector.env` | no | Backend-specific and retry configuration. Passed as env vars to the connector container. Opaque to the runtime and injector. |
| `connector.resources` | no | Optional Kubernetes resource requests/limits for the connector container. |

### Injected environment variable

The injector translates `stateProxy` spec into a **single** environment variable for the runtime, using a Docker-style syntax:

```bash
ASYA_STATE_PROXY_MOUNTS=meta:/state/meta:write=buffered;media:/state/media:write=passthrough
```

**Format**: `{name}:{path}:{options}[;{name}:{path}:{options}]*`

**Parse rules**:
1. Split on `;` to get individual mounts
2. Split on `:` to get `name`, `path`, `options`
3. Split options on `,` to get individual `key=val` pairs

**Socket path convention**: derived from the name as `/var/run/asya/state/{name}.sock`. Not configurable — convention over configuration.

**Options** (strict `key=val` format, extensible):

| Key | Values | Version | Description |
|-----|--------|---------|-------------|
| `write` | `buffered` / `passthrough` | v1 | Write buffering mode. `buffered` = SpooledTemporaryFile + PUT on close (atomic). `passthrough` = chunks flow directly to proxy. |
| `mode` | `rw` / `ro` | future | Mount mode. Default `rw`. |
| `timeout` | duration string | future | Per-operation timeout. |
| `read` | `buffered` / `auto` | future | Force read buffering for seekability. Default `auto` (proxy-driven). |

When `ASYA_STATE_PROXY_MOUNTS` is unset (local development, testing), no patching occurs. Mount paths resolve to real directories on disk.

### Injected state proxy sidecars

The injector adds state proxy containers based on the `stateProxy` spec:

```yaml
# Auto-injected by asya-injector

# Volume for state proxy Unix sockets
volumes:
  - name: state-sockets
    emptyDir: {}

# State proxy containers
containers:
  - name: asya-state-proxy-meta
    image: asya-bridges/state-proxy/redis-buffered-cas:latest
    env:
      - name: CONNECTOR_SOCKET
        value: /var/run/asya/state/meta.sock
      - name: STATE_ENDPOINT
        value: "redis://context-store:6379/0"
      - name: CAS_MAX_RETRIES
        value: "3"
      - name: CAS_RETRY_DELAY_MS
        value: "50"
    volumeMounts:
      - name: state-sockets
        mountPath: /var/run/asya/state

  - name: asya-state-proxy-media
    image: asya-bridges/state-proxy/s3-passthrough:latest
    env:
      - name: CONNECTOR_SOCKET
        value: /var/run/asya/state/media.sock
      - name: STATE_BUCKET
        value: "media-pipeline"
      - name: STATE_PREFIX
        value: "prod/"
      - name: AWS_REGION
        value: "us-east-1"
    volumeMounts:
      - name: state-sockets
        mountPath: /var/run/asya/state
```

The injector determines the `write` option value (buffered/passthrough) from the connector image name or a connector registry, and includes it in the `ASYA_STATE_PROXY_MOUNTS` env var injected into the runtime container.

---

## Python Interception Layer

### Design principle: dumb runtime, smart proxy

The runtime is a thin translator (~80 lines). It intercepts Python file I/O and forwards operations as HTTP requests over Unix socket. The proxy handles all intelligence: buffering, atomicity, CAS, retries, and backend-specific logic.

The runtime needs **no configuration** about what type of proxy is behind the socket, except the write buffering mode (provided via the `ASYA_STATE_PROXY_MOUNTS` env var).

### Activation

At startup, before loading the handler:

```python
# In asya_runtime.py, during initialization
state_proxy_mounts = os.environ.get("ASYA_STATE_PROXY_MOUNTS")
if state_proxy_mounts:
    _install_state_proxy_hooks(state_proxy_mounts)
```

When `ASYA_STATE_PROXY_MOUNTS` is unset, no patching occurs. Mount paths are real directories. Handlers work locally with zero configuration.

### What the runtime handles vs. what it forwards

| Python operation | Who handles it | Why |
|-----------------|----------------|-----|
| `f.seek()`, `f.tell()` | **Runtime** (SpooledTemporaryFile) | Operates on local buffer, proxy never sees it |
| `f.readline()`, `f.readlines()` | **Runtime** | Derived from `read()` + line splitting |
| Text encoding/decoding | **Runtime** | `"r"` mode decodes bytes from proxy to str |
| Path to key resolution | **Runtime** | Strips mount prefix, normalizes |
| `os.makedirs()` | **Runtime** (no-op) | Prefixes are virtual, nothing to forward |
| `open()` read path | **Forwarded** | `GET /keys/{key}` |
| `open()` write + `close()` | **Forwarded** | `PUT /keys/{key}` on close |
| `os.path.exists()` | **Forwarded** | `HEAD /keys/{key}` |
| `os.stat()` | **Forwarded** | `HEAD /keys/{key}` |
| `os.listdir()`, `os.scandir()` | **Forwarded** | `GET /keys/?prefix=...` |
| `os.remove()`, `os.unlink()` | **Forwarded** | `DELETE /keys/{key}` |

### What gets patched

Six functions, covering all standard Python file I/O entry points:

| Python API | Patch target | State operation |
|------------|-------------|-----------------|
| `open(path, "r"/"rb")`, `pathlib.Path.read_text/read_bytes` | `builtins.open` | `GET /keys/{key}` — returns file-like wrapper |
| `open(path, "w"/"wb")`, `pathlib.Path.write_text/write_bytes` | `builtins.open` | Buffered or passthrough write, `PUT /keys/{key}` on `close()` |
| `os.path.exists(path)`, `pathlib.Path.exists()` | `os.stat` | `HEAD /keys/{key}` — 204/404 |
| `os.listdir(path)` | `os.listdir` | `GET /keys/?prefix=...&delimiter=/` |
| `pathlib.Path.iterdir()`, `os.scandir(path)` | `os.scandir` | `GET /keys/?prefix=...&delimiter=/` |
| `os.remove(path)`, `pathlib.Path.unlink()` | `os.unlink` | `DELETE /keys/{key}` |
| `os.makedirs(path)` | `os.makedirs` | No-op for state paths (prefixes are implicit) |

The key to catching `pathlib` operations: `pathlib.Path.open()` delegates to `builtins.open`, and `pathlib.Path.exists()` delegates to `os.stat`. Patching the low-level functions catches all high-level wrappers.

`os.fspath()` is used to normalize all path arguments (`str`, `bytes`, `os.PathLike`) before mount matching.

### Read path: proxy-driven (zero config)

The runtime detects the response format and wraps accordingly:

```python
def _open_read(sock_path, key, mode):
    conn = _unix_http_connection(sock_path)
    conn.request("GET", f"/keys/{key}")
    resp = conn.getresponse()
    _raise_for_status(resp, key)

    if resp.getheader("Content-Length"):
        # Proxy sent full value — buffer locally, seekable
        buf = io.SpooledTemporaryFile(max_size=4 * 1024 * 1024)
        shutil.copyfileobj(resp, buf)
        buf.seek(0)
        resp.close()
        return _StateFile(buf, seekable=True, mode=mode)
    else:
        # Proxy is streaming — wrap response directly, not seekable
        return _StateFile(resp, seekable=False, mode=mode)
```

### Write path: env var controls buffering

```python
def _open_write(sock_path, key, mode, buffered):
    if buffered:
        return _BufferedWriteFile(sock_path, key, mode)
    else:
        return _PassthroughWriteFile(sock_path, key, mode)
```

**Buffered writes** use `SpooledTemporaryFile` (in-memory up to 4MB, then disk spill). On `close()`, the full value is sent as a single `PUT /keys/{key}` with `Content-Length`:

```python
class _BufferedWriteFile:
    """File-like object that buffers writes, flushes to proxy on close."""

    def __init__(self, sock_path, key, mode):
        self._sock_path = sock_path
        self._key = key
        self._buf = io.SpooledTemporaryFile(
            max_size=4 * 1024 * 1024,  # 4MB in-memory, then spill to disk
            mode=mode,
        )

    def write(self, data):
        return self._buf.write(data)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._buf.seek(0)
        conn = _unix_http_connection(self._sock_path)
        size = self._buf.seek(0, 2)
        self._buf.seek(0)
        conn.request("PUT", f"/keys/{self._key}", body=self._buf,
                      headers={"Content-Length": str(size)})
        resp = conn.getresponse()
        _raise_for_status(resp, self._key)
        self._buf.close()
```

**Passthrough writes** open a `PUT` with chunked transfer encoding. Each `write()` call pushes bytes toward the proxy. `close()` finalizes the transfer:

```python
class _PassthroughWriteFile:
    """File-like object that streams writes directly to proxy."""

    def __init__(self, sock_path, key, mode):
        self._conn = _unix_http_connection(sock_path)
        self._key = key
        self._conn.putrequest("PUT", f"/keys/{key}")
        self._conn.putheader("Transfer-Encoding", "chunked")
        self._conn.endheaders()

    def write(self, data):
        chunk = f"{len(data):x}\r\n".encode() + data + b"\r\n"
        self._conn.send(chunk)
        return len(data)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._conn.send(b"0\r\n\r\n")  # end chunked transfer
        resp = self._conn.getresponse()
        _raise_for_status(resp, self._key)
```

### Unix socket HTTP client

The runtime connects to proxies using `http.client` over Unix sockets. Python stdlib supports this via a custom connection class (~10 lines):

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
| `os.makedirs("/state/meta/users/123/")` | No-op (prefixes are implicit) |
| `os.listdir("/state/meta/users/")` | Prefix scan with delimiter: returns immediate children |
| `os.path.isdir("/state/meta/users/")` | `GET /keys/?prefix=users/&delimiter=/&limit=1` — true if any keys/prefixes exist |
| `os.path.isfile("/state/meta/users/123")` | `HEAD /keys/users/123` — true if key exists |
| `os.rmdir("/state/meta/users/")` | No-op or error (directories don't exist as objects) |

Example — listing and iterating:

```python
# List immediate children of a "directory"
entries = os.listdir("/state/media/users/")
# -> ["alice", "bob", "carol"]  (could be files or "subdirectories")

# Walk a tree (os.walk delegates to listdir + isdir)
for root, dirs, files in os.walk("/state/media/users/"):
    for fname in files:
        path = os.path.join(root, fname)
        async with aiofiles.open(path) as f:
            process(await f.read())
        # or sync:
        # with open(path) as f:
        #     process(f.read())
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

### Write-on-close semantics (buffered mode)

Data is sent to the proxy (and ultimately to the backend) when the file is closed, not on each `write()` call. A crash mid-write loses uncommitted data. For `buffered` connectors, this is the atomic write guarantee — either the full value is stored or nothing is.

For `passthrough` connectors, writes flow through incrementally. A crash mid-write may leave partial data in the backend.

### Size limits for buffered mode

Buffered writes use `SpooledTemporaryFile` (4MB in-memory, then disk spill). Practical limit is ~100MB — beyond that, the temp disk overhead becomes significant. For larger files, use `passthrough` connectors.

### No filesystem metadata

`os.stat()` returns synthetic values:
- `st_size`: from backend (`Content-Length` header)
- `st_mode`: fixed (`S_IFREG | 0644` for files, `S_IFDIR | 0755` for directories)
- `st_mtime`, `st_atime`, `st_ctime`: not meaningful (zero or backend-provided if available)
- `st_uid`, `st_gid`: fixed (current user)

### No file locking

Concurrent writes from multiple actor replicas to the same key are last-write-wins unless the connector supports CAS. Even though actors are designed to be single-threaded per message, this is very relevant for multi-replica actors writing to the same key — which is the fan-in case, handled by CAS connectors (see [ADR-9](#adr-9-fan-in-as-crew-actor-using-state-mounts)).

### No seek on passthrough reads

For `passthrough` connectors, `seek()` on read files is not supported — data is streamed sequentially. Calling `seek()` on a passthrough file object raises `io.UnsupportedOperation("seek")`, the same exception Python raises for non-seekable streams. For `buffered` connectors, the full value is fetched into a `SpooledTemporaryFile`, so seek works.

If seek is needed on a passthrough mount, the handler should read into a local buffer:

```python
import aiofiles, io

async with aiofiles.open("/state/media/model.bin", "rb") as f:
    buf = io.BytesIO(await f.read())  # fetch once, seek freely
    buf.seek(1024)
    header = buf.read(256)
# or sync:
# with open("/state/media/model.bin", "rb") as f:
#     buf = io.BytesIO(f.read())
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

**Workaround pattern for all gaps**: Read into a file object first, then pass the file object (not the path) to the library. This has to be clearly documented on asya side.

```python
import aiofiles

# General workaround: read state file into memory, pass to library
async with aiofiles.open("/state/media/model.pt", "rb") as f:
    data = await f.read()  # intercepted, streamed from proxy
# or sync:
# with open("/state/media/model.pt", "rb") as f:
#     data = f.read()

# Then use library with in-memory data
img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
arr = np.frombuffer(data, dtype=np.float32)
model = torch.jit.load(io.BytesIO(data))
df = pd.read_parquet(io.BytesIO(data))
```

This is documented behavior, not a bug. The Python-level interception is a deliberate design choice: it covers the vast majority of use cases without requiring elevated container privileges (FUSE/SYS_ADMIN), kernel modules, or LD_PRELOAD tricks.

---

## Local Development

When `ASYA_STATE_PROXY_MOUNTS` is unset (local development, testing), no patching occurs. Mount paths resolve to real directories on disk:

```python
# This code works identically in both environments:
async with aiofiles.open("/state/meta/user/123", "w") as f:
    await f.write(json.dumps(context))
# or sync:
# with open("/state/meta/user/123", "w") as f:
#     json.dump(context, f)

# Local: writes to /state/meta/user/123 on disk (create the directory first)
# Deployed: intercepted, PUT to proxy -> Redis
```

For local development, create the mount directories:
```bash
mkdir -p /state/meta /state/media
```

Or use a project-local convention:
```bash
mkdir -p ./state/meta ./state/media
# Set ASYA_STATE_PROXY_MOUNTS with local paths if testing the interception layer
```

No conditional imports, no environment detection, no mock objects. The same handler code runs locally and in production. Exception behavior is also identical: `FileNotFoundError` on missing keys works the same with real files and proxied files.

---

## Examples

### Agentic per-user context storage

```python
import aiofiles, json, os

async def handle(payload):
    user_id = payload["user_id"]
    context_path = f"/state/meta/context/{user_id}"

    # Load existing context (or start fresh)
    try:
        async with aiofiles.open(context_path) as f:
            context = json.loads(await f.read())
    except FileNotFoundError:
        context = {"history": [], "preferences": {}}

    # Process message, update context
    context["history"].append(payload["message"])
    response = await call_llm(context)
    context["preferences"].update(response.get("learned_prefs", {}))

    # Save updated context
    async with aiofiles.open(context_path, "w") as f:
        await f.write(json.dumps(context))

    return {"reply": response["text"]}
```

Sync equivalent:
```python
# with open(context_path) as f:
#     context = json.load(f)
# with open(context_path, "w") as f:
#     json.dump(context, f)
```

```yaml
spec:
  stateProxy:
    - name: meta
      mount:
        path: /state/meta
      connector:
        image: asya-bridges/state-proxy/redis-buffered-cas:latest
        env:
          - name: STATE_ENDPOINT
            value: "redis://context-store:6379/0"
```

### Media file storage

```python
import aiofiles
from PIL import Image
import io

async def handle(payload):
    # Read input image from object store
    async with aiofiles.open(f"/state/media/uploads/{payload['image_id']}.jpg", "rb") as f:
        img = Image.open(io.BytesIO(await f.read()))

    # Process
    result = transform(img)

    # Write result back to object store
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    async with aiofiles.open(f"/state/media/results/{payload['image_id']}.png", "wb") as f:
        await f.write(buf.getvalue())

    return {"status": "processed", "output_key": f"results/{payload['image_id']}.png"}
```

```yaml
spec:
  stateProxy:
    - name: media
      mount:
        path: /state/media
      connector:
        image: asya-bridges/state-proxy/s3-buffered-lww:latest
        env:
          - name: STATE_BUCKET
            value: "media-pipeline"
          - name: STATE_PREFIX
            value: "v1/"
          - name: AWS_REGION
            value: "us-east-1"
```

### Streaming video processing (passthrough)

```python
import aiofiles

async def handle(payload):
    video_id = payload["video_id"]

    # Stream large video file — not buffered in memory
    async with aiofiles.open(f"/s3/video/raw/{video_id}.mp4", "rb") as f:
        while chunk := await f.read(8192):
            await process_chunk(chunk)

    # Write processed output — streams directly to S3 via multipart upload
    async with aiofiles.open(f"/s3/video/processed/{video_id}.mp4", "wb") as f:
        for chunk in generate_processed_chunks():
            await f.write(chunk)

    return {"status": "processed"}
```

```yaml
spec:
  stateProxy:
    - name: video
      mount:
        path: /states3
      connector:
        image: asya-bridges/state-proxy/s3-passthrough:latest
        env:
          - name: STATE_BUCKET
            value: "video-pipeline"
          - name: STATE_PREFIX
            value: "prod/"
          - name: AWS_REGION
            value: "us-east-1"
```

### Session files with multiple stores

```python
import aiofiles, json, os, pickle

async def handle(payload):
    session_id = payload["session_id"]

    # Fast KV for session metadata (Redis, buffered + CAS)
    meta_path = f"/state/meta/sessions/{session_id}"
    try:
        async with aiofiles.open(meta_path) as f:
            meta = json.loads(await f.read())
    except FileNotFoundError:
        meta = {"step": 0, "created": payload["timestamp"]}

    # Object store for large artifacts (S3, buffered)
    artifact_dir = f"/state/media/sessions/{session_id}"
    existing = os.listdir(artifact_dir) if os.path.isdir(artifact_dir) else []

    # Process
    result, artifact = await process_step(payload, meta, existing)

    # Write artifact to S3
    async with aiofiles.open(f"{artifact_dir}/step-{meta['step']}.pkl", "wb") as f:
        await f.write(pickle.dumps(artifact))

    # Update session metadata in Redis
    meta["step"] += 1
    async with aiofiles.open(meta_path, "w") as f:
        await f.write(json.dumps(meta))

    return result
```

```yaml
spec:
  stateProxy:
    - name: meta
      mount:
        path: /state/meta
      connector:
        image: asya-bridges/state-proxy/redis-buffered-cas:latest
        env:
          - name: STATE_ENDPOINT
            value: "redis://sessions:6379/0"
    - name: media
      mount:
        path: /state/media
      connector:
        image: asya-bridges/state-proxy/s3-buffered-lww:latest
        env:
          - name: STATE_BUCKET
            value: "session-artifacts"
          - name: STATE_PREFIX
            value: "prod/"
```

---

## Implementation Plan

### Phase 1: Connector interface and framework

- Define `StateProxyConnector` Python interface (finalized above)
- Define HTTP-over-Unix-socket protocol with error mapping
- Build connector base/framework with shared socket listener, health checks, graceful shutdown
- Implement `s3-buffered-lww` (first connector — simplest, no CAS)
- Implement `redis-buffered-cas` (second connector — with CAS and internal retries)

### Phase 2: Runtime interception

- Add state proxy hook installation to `asya_runtime.py` (~80 lines)
- Implement `_StateFile` read wrapper (auto-detects buffered vs passthrough from response)
- Implement `_BufferedWriteFile` and `_PassthroughWriteFile` wrappers
- Implement `ASYA_STATE_PROXY_MOUNTS` env var parser (semicolon/colon/comma format)
- Implement `_raise_for_status` error translation
- Implement Unix socket HTTP client
- Implement mount resolution and function patching
- Unit tests for interception layer

### Phase 3: Injector and XRD integration

- Add `stateProxy` field to AsyncActor XRD with `name`, `mount`, `connector` sub-trees
- Update injector to add state proxy sidecar containers (`asya-state-proxy-{name}`)
- Update injector to add `state-sockets` emptyDir volume
- Update injector to generate `ASYA_STATE_PROXY_MOUNTS` env var from spec
- Update Crossplane compositions

### Phase 4: Additional connectors

- Implement `s3-passthrough` (streaming connector)
- Implement `s3-buffered-cas` (S3 with CAS via ETag/conditional PutObject)
- Implement `nats-kv-buffered-cas` (NATS KV with revision-based CAS)

### Phase 5: Testing and documentation

- Component tests: runtime <-> connector over Unix socket
- Integration tests: full pipeline with state access
- Test CAS conflict handling (both connector-level and asya-level retries)
- Test passthrough streaming for large files
- Document connector implementation guide for platform teams
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

**Rationale**: The strongest argument is local development parity. With FS emulation, the handler code `open("/state/meta/key", "w")` works identically on a developer's laptop (real files) and in production (intercepted, routed to Redis/S3). No mocks, no conditional imports, no environment detection. The handler author does not need to know Asya exists.

The documented gaps (C extensions that bypass Python's `open()`) are narrow, have standard workarounds (pass file objects instead of paths), and affect edge cases rather than the primary use cases.

### ADR-2: Python-level patching vs. FUSE vs. LD_PRELOAD vs. seccomp

**Context**: Multiple approaches exist for intercepting file operations.

| Approach | Coverage | Privileges | Complexity | K8s compatibility |
|----------|----------|-----------|------------|-------------------|
| **Python patching** | **builtins.open, os.*, pathlib** | **None** | **~80 lines** | **Any cluster** |
| FUSE | All operations (kernel-level) | SYS_ADMIN, /dev/fuse, mountPropagation: Bidirectional | ~1000 lines + kernel interaction | Requires privileged pods |
| LD_PRELOAD | All libc calls | None | ~400 lines C | Any cluster |
| seccomp_unotify | All syscalls | CAP_SYS_ADMIN or pre-installed profile | ~800 lines C | Requires security policy changes |

**Decision**: Python-level patching.

**Rationale**: The target workloads are Python actor handlers. For the documented use cases (JSON, pickle, torch, PIL, pandas CSV, HuggingFace), all operations go through `builtins.open`. The few gaps (OpenCV, numpy.fromfile, pyarrow internals) have simple workarounds. Python patching requires zero privileges, works in any Kubernetes cluster (including hardened multi-tenant clusters with PodSecurityStandards), and adds minimal code to the runtime.

FUSE provides complete coverage but requires privileged pods — unacceptable for multi-tenant production clusters. LD_PRELOAD is a reasonable middle ground but requires a compiled C shared library, adding build and maintenance complexity. seccomp_unotify requires security policy changes.

If a future use case requires complete syscall interception (e.g., Go-based actor runtimes), LD_PRELOAD or FUSE can be revisited for that specific runtime. The connector protocol is transport-agnostic — the same connectors work regardless of interception method.

### ADR-3: State proxy sidecar vs. extending asya-sidecar

**Context**: Backend-specific state proxy logic (S3 SDK calls, Redis commands) must run somewhere. Two options: (a) extend `asya-sidecar` with state proxy endpoints, or (b) deploy separate state proxy sidecar containers.

| Approach | Modularity | Sidecar complexity | Independent versioning | User-extensible |
|----------|-----------|-------------------|----------------------|----------------|
| Extend asya-sidecar | Low (monolith) | High (message routing + state proxy + N backends) | No (coupled releases) | No |
| **State proxy sidecars** | **High (one container per backend+guarantees)** | **Unchanged** | **Yes** | **Yes (custom connectors)** |

**Decision**: Separate state proxy sidecars.

**Rationale**: `asya-sidecar` has a focused responsibility: message routing between queues and the runtime. Adding state proxy logic with pluggable backends (S3, GCS, Redis, NATS, DynamoDB) would significantly increase its complexity, binary size, dependency tree, and attack surface. Separate connectors keep each component focused and independently deployable. Platform teams can build custom connectors for proprietary storage systems by implementing the `StateProxyConnector` interface.

### ADR-4: HTTP over Unix socket vs. custom protocol

**Context**: The runtime needs to communicate with state proxy connectors. Options: custom JSON-RPC protocol, gRPC, or HTTP over Unix socket.

**Decision**: HTTP over Unix socket.

**Rationale**: HTTP gives streaming for free (chunked transfer encoding), uses Python stdlib (`http.client`), and is universally understood. The RESTful interface (`GET /keys/{key}`, `PUT /keys/{key}`, `HEAD /keys/{key}`) maps naturally to KV/object store semantics. Any language can implement a connector with an HTTP server library. No custom serialization, no protobuf compilation, no RPC framework dependencies.

### ADR-5: Write-on-close (buffered) vs. write-through

**Context**: When the handler calls `f.write(data)`, should the data be sent to the proxy immediately (write-through) or buffered and sent on `f.close()` (write-on-close)?

**Decision**: Configurable per mount — `write=buffered` (write-on-close) or `write=passthrough` (streaming writes).

**Rationale**: For KV and object store backends, the natural unit of storage is a complete value, not a byte stream. S3 PutObject requires knowing the content upfront (or using multipart upload). Redis SET stores a complete value. Buffering writes and flushing on close matches these semantics for most use cases.

For large files (video, datasets), buffering the entire value is impractical. The `write=passthrough` option enables streaming writes via chunked transfer encoding, with the proxy handling multipart upload internally.

The write mode is specified per mount in the `ASYA_STATE_PROXY_MOUNTS` env var. The runtime creates the appropriate write wrapper at `open()` time.

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

**Decision**: Fan-in crew actor (`x-fanin`) uses state mounts with CAS-capable connectors.

**Rationale**: The state mount provides the storage interface. The fan-in handler reads/writes partial aggregation state through `open()` and `os.path.exists()` like any other actor. CAS semantics (needed for concurrent fan-in from multiple pods) are hidden inside the connector:

1. Handler calls `read()` — connector internally stores revision
2. Handler modifies value
3. Handler calls `write()` — connector uses stored revision for conditional write
4. On conflict: connector retries internally (Layer 1), then raises error for asya-level retry (Layer 2)

The handler author doesn't need to know CAS exists. The same handler code works with a CAS connector (concurrent safe) or a last-write-wins connector (single-writer scenarios).

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

### ADR-11: Dumb runtime, smart proxy

**Context**: The runtime needs to handle file I/O interception. Two approaches: (a) the runtime decides buffering/CAS behavior based on configuration, or (b) the runtime is a thin translator that forwards operations to the proxy, which decides everything.

| Approach | Runtime complexity | Configuration needed | Adding new guarantee types |
|----------|-------------------|---------------------|---------------------------|
| Smart runtime | High (multiple file wrappers per type, CAS logic, retry logic) | Per-mount type config | Requires runtime changes |
| **Dumb runtime** | **Low (~80 lines, one read wrapper, two write wrappers)** | **One env var with write mode** | **New proxy connector only** |

**Decision**: Dumb runtime, smart proxy.

**Rationale**: The runtime's philosophy is "single file, zero dependencies, minimal code." Pushing all intelligence into the proxy keeps the runtime at ~80 lines of interception code. The proxy decides buffering, atomicity, CAS behavior, and retries. Adding a new guarantee type means building a new proxy connector — no runtime changes needed.

The runtime needs exactly one piece of per-mount configuration: write buffering mode (`write=buffered` or `write=passthrough`). For reads, the proxy's response format (Content-Length vs chunked) tells the runtime what to do. This asymmetry is fundamental: reads can be auto-detected from the response, but writes require choosing the upload strategy before the first `write()` call.

### ADR-12: Absolute mount paths

**Context**: Mount paths could be relative to workdir (`./cache/`) or absolute (`/state/cache/`).

**Decision**: Absolute mount paths (e.g., `/state/meta`, `/state/media`).

**Rationale**: Absolute paths are unambiguous — they don't depend on the working directory, which may vary across container configurations. The `runtimeMount` field in the XRD is renamed to `mount.path` to clarify it specifies the path inside the runtime container. The `/state/` prefix convention makes it clear these are managed state mounts, not arbitrary filesystem paths.

### ADR-13: CAS hidden inside read/write interface

**Context**: CAS (compare-and-swap) is needed for concurrent fan-in writes. Two approaches: (a) expose CAS as separate interface methods (`get_versioned()`, `put_if_match()`), or (b) hide CAS inside the regular `read()`/`write()` methods.

| Approach | Handler complexity | Interface surface | Retry handling |
|----------|-------------------|------------------|----------------|
| Explicit CAS methods | Handler must use CAS API | 8 methods (6 base + 2 CAS) | Handler-managed |
| **Hidden CAS** | **Handler uses open/read/write** | **6 methods** | **Two-layer (connector + asya)** |

**Decision**: CAS hidden inside `read()`/`write()`.

**Rationale**: The `read()` method internally stores the revision. The `write()` method internally uses the stored revision for conditional write. On conflict, the connector retries internally (configurable `CAS_MAX_RETRIES`). If retries exhaust, it raises `FileExistsError` (HTTP 409), which propagates through the runtime to the sidecar, triggering asya-level message requeue with exponential backoff.

The handler code is identical whether using a CAS connector or a last-write-wins connector. No CAS-awareness leaks into the handler or the runtime.

### ADR-14: Single environment variable for mount configuration

**Context**: The runtime needs mount configuration (paths, socket paths, write mode). Two approaches: (a) multiple env vars per mount (`ASYA_STATE_PROXY_{name}_SOCKET`, `ASYA_STATE_PROXY_{name}_BUFFERED`, etc.), or (b) a single env var with Docker-style syntax.

**Decision**: Single `ASYA_STATE_PROXY_MOUNTS` env var with structured format.

**Format**: `{name}:{path}:{options}[;{name}:{path}:{options}]*`

Example: `meta:/state/meta:write=buffered;media:/state/media:write=passthrough`

**Rationale**: One env var is cleaner than 2N+1 env vars (for N mounts). The Docker-style `source:destination:options` format is familiar. Socket paths are derived by convention (`/var/run/asya/state/{name}.sock`), eliminating the most verbose part. Options use strict `key=val` format with `,` separator, extensible for future options (`mode=rw`, `timeout=30s`, `read=buffered`).

---

## Open Questions

1. **Connector health checks**: How does the runtime know if a connector is ready before the handler starts? Options: readiness probe on the connector socket, or the runtime retries connection on first state access.

2. **State store lifecycle**: Who provisions the backend (Redis, S3 bucket, etc.)? Options: user-managed (BYO), Crossplane-managed (auto-provision with the actor), or Helm-chart-managed.

3. **TTL and cleanup**: For KV backends (Redis, NATS), should keys have automatic TTL? Configurable per mount via the options field (e.g., `ttl=3600`)? This prevents unbounded growth from orphaned state.

4. **Binary vs. text mode**: Should `open(path, "r")` (text mode) perform encoding/decoding, or should the connector always return raw bytes? Text mode with UTF-8 is the expected default for most use cases. The runtime handles encoding, not the connector.

5. **Connector registry**: How does the injector know the write mode for a given connector image? Options: (a) derive from image name convention (`*-buffered-*` vs `*-passthrough`), (b) connector registry ConfigMap mapping image names to capabilities, (c) well-known label on the connector image.

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
