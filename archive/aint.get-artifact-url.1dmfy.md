---
title: Implement xattr-based metadata API for state proxy (getxattr/listxattr/setxattr)
status: merged
priority: 1
parent: g5bkc
tags:
  - topic:state-proxy
  - topic:a2a
  - topic:artifacts
  - topic:xattr
  - pr:249
---

## Motivation

Actors that produce files (PDFs, images, model outputs) need to reference them in
A2A artifacts. Today an actor can `open("/state/media/report.pdf", "wb")` and write
content — but has no way to obtain backend metadata: external URL, content hash,
presigned URLs, etc.

The actor doesn't (and shouldn't) know the storage backend configuration (bucket
name, prefix, region, endpoint). The state proxy connector owns all that. We need
a FS-native API for actors to read and write backend metadata using **only Python
stdlib** — no custom imports (asya_runtime is ConfigMap-injected, not a pip package).

**Cross-reference**: A2A RFC (1c0d) Section 5.3.1, State Proxy RFC (1dmf) Section
"Extended Attributes (xattr)".

## Current Architecture (Execution Context)

An agent executing this task must understand the state proxy stack:

```
Handler code                          asya_runtime.py                  State proxy sidecar
open("/state/media/k", "w")  ──>  builtins.open patch  ──>  PUT /keys/k  ──>  connector  ──> S3
os.stat("/state/media/k")    ──>  os.stat patch        ──>  HEAD /keys/k ──>  connector  ──> S3
os.listdir("/state/media/")  ──>  os.listdir patch     ──>  GET /keys/?  ──>  connector  ──> S3
os.remove("/state/media/k")  ──>  os.unlink patch      ──>  DELETE /keys/k -> connector  ──> S3

NEW (this task):
os.listxattr(path)           ──>  os.listxattr patch   ──>  GET /meta/k  ──>  connector.listxattr
os.getxattr(path, attr)      ──>  os.getxattr patch    ──>  GET /meta/k?attr=a -> connector.getxattr
os.setxattr(path, attr, val) ──>  os.setxattr patch    ──>  PUT /meta/k?attr=a -> connector.setxattr
```

### Key files and their roles

| File | Python | Role |
|------|--------|------|
| `src/asya-state-proxy/asya_state_proxy/interface.py` | >=3.13 | ABC with 6 abstract methods (`read`, `write`, `exists`, `stat`, `list`, `delete`). New xattr methods go here as non-abstract. |
| `src/asya-state-proxy/asya_state_proxy/server.py` | >=3.13 | `ConnectorServer` (Unix socket HTTP). `_make_handler` creates `_Handler` with `do_GET`, `do_PUT`, `do_HEAD`, `do_DELETE`. Routes `/keys/{key}` and `/keys/?prefix=`. Error mapping: `_ERROR_MAP` dict maps exception types to HTTP status codes. Helper functions: `_json_ok`, `_json_error`, `_handle_connector_error`. New `/meta/{key}` routes go here. |
| `src/asya-state-proxy/asya_state_proxy/connectors/s3_passthrough/connector.py` | >=3.13 | `S3Passthrough(StateProxyConnector)`. Has `self._bucket`, `self._prefix`, `self._s3` (boto3 client). `_full_key(key)` prepends prefix. |
| `src/asya-state-proxy/asya_state_proxy/connectors/s3_buffered_cas/connector.py` | >=3.13 | `S3BufferedCAS(StateProxyConnector)`. Same as passthrough + `self._etags: dict[str, str]` for CAS. ETags cached on read, used for conditional write. |
| `src/asya-state-proxy/asya_state_proxy/connectors/s3_buffered_lww/connector.py` | >=3.13 | `S3BufferedLWW(StateProxyConnector)`. Same S3 structure, no ETag tracking. |
| `src/asya-state-proxy/asya_state_proxy/connectors/redis_buffered_cas/connector.py` | >=3.13 | `RedisBufferedCAS(StateProxyConnector)`. Has `self._redis` (redis client), `self._prefix`. Uses WATCH/MULTI/EXEC for CAS. |
| `src/asya-runtime/asya_runtime.py` | **>=3.7** | Single file, zero dependencies. Patches `builtins.open`, `os.stat`, `os.listdir`, `os.unlink`, `os.makedirs` inside `_install_state_proxy_hooks(mounts_str)`. Closures capture `mounts` list. Helpers: `_resolve_mount(path, mounts)` → `(mount, key)`, `_UnixHTTPClient(sock_path)` for HTTP over Unix socket, `_raise_for_status(resp, key)` maps HTTP errors to Python exceptions. **Must use Python 3.7+ compatible syntax**: `typing.Dict`/`List`, `# type:` comments, no `X | Y` unions, no `list[str]`. |

### Runtime patching pattern (follow exactly)

All patches in `_install_state_proxy_hooks` follow this pattern:
1. Store original: `_original_foo = os.foo`
2. Define closure: `def _patched_foo(path, ...)`
3. Call `_resolve_mount(path, mounts)` → `(mount, key)` or `(None, None)`
4. If `mount is None`: fall through to `_original_foo(path, ...)`
5. If mount matched: create `_UnixHTTPClient(mount["socket"])`, make HTTP request, parse response
6. At end of function: `os.foo = _patched_foo`

### Mount configuration

`ASYA_STATE_PROXY_MOUNTS` env var format: `{name}:{path}:{options}[;...]`
Example: `meta:/state/meta:write=buffered;media:/state/media:write=passthrough`

Each mount becomes a dict: `{"name": "media", "path": "/state/media/", "socket": "/var/run/asya/state/media.sock", "write_mode": "passthrough"}`

### Existing test patterns

**Server tests** (`src/asya-state-proxy/tests/test_server.py`):
- `StubConnector` in-memory implementation of `StateProxyConnector`
- `server_socket` fixture: creates `ConnectorServer` on tmp Unix socket, runs in thread
- `_request(socket_path, method, path, body, headers)` helper for HTTP calls
- Tests: `test_put_then_get_returns_same_data`, `test_get_missing_key_returns_404`, etc.
- `StubConnector` needs xattr methods added for new tests.

**Runtime tests** (`src/asya-runtime/tests/test_state_proxy.py`):
- `_MockConnectorHandler` — HTTP handler with in-memory KV store
- Runs mock server on Unix socket, patches `_install_state_proxy_hooks`
- Tests patched `builtins.open`, `os.stat`, `os.listdir`, etc.
- Mock handler needs `/meta/` route support added for new tests.

### Error mapping conventions

**Server** (`_ERROR_MAP` in `server.py`):
```python
_ERROR_MAP = {
    FileNotFoundError: (404, "key_not_found"),
    FileExistsError: (409, "conflict"),
    ValueError: (400, "bad_request"),
    PermissionError: (403, "permission_denied"),
    ConnectionError: (503, "unavailable"),
    TimeoutError: (504, "timeout"),
}
```
Add: `KeyError: (400, "unsupported_attribute")`. `PermissionError` → 403 already mapped.

**Runtime** (`_STATUS_TO_EXCEPTION` in `asya_runtime.py`):
```python
_STATUS_TO_EXCEPTION = {
    404: FileNotFoundError, 409: FileExistsError, 412: FileExistsError,
    400: ValueError, 403: PermissionError, 500: OSError, 503: ConnectionError,
    504: TimeoutError,
}
```
For xattr patches: 400 → `OSError(errno.ENODATA)`, 403 → `PermissionError`
(handle explicitly before `_raise_for_status` since 400 normally maps to
`ValueError`, not `OSError`).

## Design: xattr as Backend Metadata API

Extended attributes (`os.getxattr`/`os.listxattr`/`os.setxattr`) are the standard
Linux filesystem mechanism for per-file metadata. They map perfectly to "ask the
backend about a stored object" — and they're Python stdlib on Linux + macOS.

### Handler API

```python
import os

# Write a file (existing pattern — intercepted open())
with open("/state/media/report.pdf", "wb") as f:
    f.write(pdf_content)

# Discover available attributes
attrs = os.listxattr("/state/media/report.pdf")
# → ["user.asya.url", "user.asya.presigned_url", "user.asya.etag", ...]

# Read the canonical backend URL
url = os.getxattr("/state/media/report.pdf", "user.asya.url")
# → b"s3://my-bucket/prefix/media/report.pdf"

# Read a presigned URL for A2A artifact delivery
presigned = os.getxattr("/state/media/report.pdf", "user.asya.presigned_url")
# → b"https://my-bucket.s3.amazonaws.com/prefix/...?X-Amz-Signature=..."

# Set content type (writable attribute)
os.setxattr("/state/media/report.pdf", "user.asya.content_type",
            b"application/pdf")
```

### Namespace Convention: `user.asya.{attr}`

Linux xattr has four namespaces (`user`, `system`, `security`, `trusted`). Only
`user.*` is accessible to unprivileged processes. We sub-namespace under `asya`
to prevent collisions:

- `user.` — required Linux xattr namespace prefix
- `asya.` — application sub-namespace
- `{attr}` — bare attribute name (`url`, `etag`, `content_type`, etc.)

The runtime strips `user.asya.` before sending to the connector, and prepends it
when returning results from `os.listxattr`.

### Attribute Catalog

| Attribute | R/W | Returns | Description | Backends |
|-----------|-----|---------|-------------|----------|
| `url` | R | Canonical backend URI | `s3://bucket/key`, `gs://bucket/key` | S3, GCS, Azure |
| `presigned_url` | R | Time-limited HTTPS URL | Unauthenticated access, configurable TTL | S3, GCS, Azure |
| `etag` | R | Content hash | Entity tag from backend | S3, GCS |
| `content_type` | RW | MIME type | e.g. `application/pdf` | S3, GCS, Azure |
| `version` | R | Version/revision ID | S3 version ID, NATS KV revision | S3*, NATS KV |
| `storage_class` | R | Storage tier | `STANDARD`, `GLACIER`, etc. | S3 |
| `ttl` | RW | Seconds until expiry | Key TTL in Redis | Redis |

`R` = read-only (computed by backend). `os.setxattr` raises `PermissionError`.
`RW` = read-write. `*` = only if S3 bucket versioning is enabled.

### Attribute Availability by Connector

| Connector | `url` | `presigned_url` | `etag` | `content_type` | `version` | `ttl` |
|-----------|-------|-----------------|--------|----------------|-----------|-------|
| s3-passthrough | R | R | R | RW | R* | - |
| s3-buffered-cas | R | R | R | RW | R* | - |
| s3-buffered-lww | R | R | R | RW | R* | - |
| redis-buffered-cas | - | - | - | - | - | RW |
| nats-kv-buffered-cas | - | - | - | - | R | - |

`-` = not supported. `os.getxattr` raises `OSError(ENODATA)`. `os.listxattr`
omits from result.

### Cross-Platform Story

**Platform availability**: `os.getxattr`/`os.listxattr`/`os.setxattr`:
- Linux: available (native syscall)
- macOS: available (native syscall, Darwin 8.0+)
- Windows: NOT available (`AttributeError`)

**K8s runtime (Linux)** — full support:
- Runtime patches all three xattr functions for state mount paths
- `user.asya.*` attributes → HTTP to connector `/meta/` endpoints
- Non-state paths and non-`user.asya.*` attributes fall through to native

**Local dev (Linux/macOS)** — graceful degradation:
- `os.getxattr` exists natively but no `user.asya.*` attributes are set on real
  files → `OSError(ENODATA)`. `os.listxattr` returns empty list (or other real
  xattrs, never `user.asya.*`).
- This is expected: local files don't have backend URLs. Actors should guard:
  ```python
  try:
      url = os.getxattr(path, "user.asya.url").decode()
  except OSError:
      url = None  # xattr not available locally
  ```
- For test simulation: `asya-testing` provides a pytest fixture.

**Local dev (Windows)** — `os.*xattr` doesn't exist:
- `AttributeError` on access. Guard with `hasattr(os, "getxattr")` or catch both
  `AttributeError` and `OSError`.
- `asya-testing` fixture defines the functions on Windows and returns `file://`
  URIs. Not a blocker — Windows is minority for container-targeted dev.

## Layer Changes

### 1. Connector Interface (`interface.py`)

Add three non-abstract methods (connectors opt in by overriding):

```python
class StateProxyConnector(ABC):
    # ... existing 6 abstract methods ...

    def listxattr(self, key: str) -> list[str]:
        """List supported metadata attributes (bare names, no prefix)."""
        return []

    def getxattr(self, key: str, attr: str) -> str:
        """Read a metadata attribute value.
        Raises KeyError (unsupported) or FileNotFoundError (key missing)."""
        raise KeyError(f"{type(self).__name__}: unsupported attr {attr}")

    def setxattr(self, key: str, attr: str, value: str) -> None:
        """Set a metadata attribute.
        Raises KeyError (unsupported), PermissionError (read-only),
        or FileNotFoundError (key missing)."""
        raise KeyError(f"{type(self).__name__}: unsupported attr {attr}")
```

### 2. S3 Connectors (all three)

```python
_S3_ATTRS = ["url", "presigned_url", "etag", "content_type", "version",
             "storage_class"]
_S3_WRITABLE = {"content_type"}

def listxattr(self, key: str) -> list[str]:
    return list(_S3_ATTRS)

def getxattr(self, key: str, attr: str) -> str:
    full_key = self._full_key(key)
    if attr == "url":
        return f"s3://{self._bucket}/{full_key}"
    if attr == "presigned_url":
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": full_key},
            ExpiresIn=int(os.environ.get("STATE_PRESIGN_TTL", "3600")),
        )
    if attr == "etag":
        resp = self._s3.head_object(Bucket=self._bucket, Key=full_key)
        return resp["ETag"]
    if attr == "content_type":
        resp = self._s3.head_object(Bucket=self._bucket, Key=full_key)
        return resp.get("ContentType", "application/octet-stream")
    if attr == "version":
        resp = self._s3.head_object(Bucket=self._bucket, Key=full_key)
        return resp.get("VersionId", "")
    if attr == "storage_class":
        resp = self._s3.head_object(Bucket=self._bucket, Key=full_key)
        return resp.get("StorageClass", "STANDARD")
    raise KeyError(f"Unsupported attribute: {attr}")

def setxattr(self, key: str, attr: str, value: str) -> None:
    if attr not in _S3_WRITABLE:
        raise PermissionError(f"Attribute {attr} is read-only")
    if attr == "content_type":
        full_key = self._full_key(key)
        self._s3.copy_object(
            Bucket=self._bucket, Key=full_key,
            CopySource={"Bucket": self._bucket, "Key": full_key},
            ContentType=value, MetadataDirective="REPLACE",
        )
```

Cost profile: `url` = zero API calls (string concat). `presigned_url` = signing
call (local crypto, no network). `etag`/`content_type`/`version`/`storage_class`
= HEAD request.

### 3. HTTP Server (`server.py`)

New `/meta/` route family:

| Request | Handler | Response |
|---------|---------|----------|
| `GET /meta/{key}` | `listxattr(key)` | `{"attrs": ["url", ...]}` |
| `GET /meta/{key}?attr=url` | `getxattr(key, "url")` | `{"attr": "url", "value": "s3://..."}` |
| `PUT /meta/{key}?attr=content_type` | `setxattr(key, "content_type", val)` | 204 |

Error mapping:
- `KeyError` → 400 (unsupported attribute)
- `PermissionError` → 403 (read-only attribute)
- `FileNotFoundError` → 404 (key not found)

### 4. Runtime (`asya_runtime.py`)

Patch `os.getxattr`, `os.listxattr`, `os.setxattr` in `_install_state_proxy_hooks`:

```python
_original_getxattr = getattr(os, "getxattr", None)
_original_listxattr = getattr(os, "listxattr", None)
_original_setxattr = getattr(os, "setxattr", None)

_ASYA_PREFIX = "user.asya."

def _patched_getxattr(path, attribute, *args, **kwargs):
    attr_str = attribute.decode() if isinstance(attribute, bytes) else attribute
    if attr_str.startswith(_ASYA_PREFIX):
        mount, key = _resolve_mount(path, mounts)
        if mount is not None:
            bare = attr_str[len(_ASYA_PREFIX):]
            conn = _UnixHTTPClient(mount["socket"])
            conn.request("GET", f"/meta/{key}?attr={bare}")
            resp = conn.getresponse()
            if resp.status == 400:
                raise OSError(errno.ENODATA, f"Attribute not supported: {bare}")
            if resp.status == 403:
                raise PermissionError(f"Attribute is read-only: {bare}")
            _raise_for_status(resp, key)
            body = json.loads(resp.read())
            conn.close()
            return body["value"].encode("utf-8")
    if _original_getxattr is not None:
        return _original_getxattr(path, attribute, *args, **kwargs)
    raise OSError(errno.ENOTSUP, "Extended attributes not supported")

def _patched_listxattr(path=None, **kwargs):
    if path is not None:
        mount, key = _resolve_mount(path, mounts)
        if mount is not None:
            conn = _UnixHTTPClient(mount["socket"])
            conn.request("GET", f"/meta/{key}")
            resp = conn.getresponse()
            _raise_for_status(resp, key)
            body = json.loads(resp.read())
            conn.close()
            return [f"{_ASYA_PREFIX}{a}" for a in body["attrs"]]
    if _original_listxattr is not None:
        return _original_listxattr(path, **kwargs)
    return []

def _patched_setxattr(path, attribute, value, *args, **kwargs):
    attr_str = attribute.decode() if isinstance(attribute, bytes) else attribute
    if attr_str.startswith(_ASYA_PREFIX):
        mount, key = _resolve_mount(path, mounts)
        if mount is not None:
            bare = attr_str[len(_ASYA_PREFIX):]
            val_str = value.decode() if isinstance(value, bytes) else value
            body = json.dumps({"value": val_str}).encode()
            conn = _UnixHTTPClient(mount["socket"])
            conn.request("PUT", f"/meta/{key}?attr={bare}",
                         body=body,
                         headers={"Content-Length": str(len(body)),
                                  "Content-Type": "application/json"})
            resp = conn.getresponse()
            if resp.status == 400:
                raise OSError(errno.ENODATA, f"Attribute not supported: {bare}")
            if resp.status == 403:
                raise PermissionError(f"Attribute is read-only: {bare}")
            _raise_for_status(resp, key)
            conn.close()
            return
    if _original_setxattr is not None:
        return _original_setxattr(path, attribute, value, *args, **kwargs)
    raise OSError(errno.ENOTSUP, "Extended attributes not supported")

os.getxattr = _patched_getxattr
os.listxattr = _patched_listxattr
os.setxattr = _patched_setxattr
```

### Rejected Alternatives

**`from asya_runtime import state_url`** — Impossible. Runtime is ConfigMap-injected,
not a pip package. Handler code cannot import from it.

**`builtins.state_url` (magic builtin)** — Non-standard, undiscoverable, `NameError`
locally (worse than `OSError`). Patched calls should be EXISTING stdlib functions.

**`os.readlink` (virtual symlink)** — `os.path.realpath()` calls `os.readlink()`
internally — patching breaks it. URL strings corrupt code expecting paths.

**ABI yield protocol** — Only works in generators, overloads message metadata
semantics, awkward path-inside-dotpath syntax.

## Implementation Plan

### Phase 1: Interface & Server

1. **`src/asya-state-proxy/asya_state_proxy/interface.py`** — Add `listxattr`,
   `getxattr`, `setxattr` to `StateProxyConnector` (non-abstract, default raises)
2. **`src/asya-state-proxy/asya_state_proxy/server.py`** — Add `/meta/{key}` route
   handlers: `do_GET` dispatches to `listxattr`/`getxattr`, `do_PUT` dispatches to
   `setxattr`. Add `KeyError` → 400 and `PermissionError` → 403 to `_ERROR_MAP`.

### Phase 2: S3 Connectors

3. **`src/asya-state-proxy/asya_state_proxy/connectors/s3_passthrough/connector.py`**
   — Override `listxattr`/`getxattr`/`setxattr` on `S3Passthrough`. Attrs: `url`
   (string concat), `presigned_url` (`generate_presigned_url`), `etag`
   (`head_object`), `content_type` (head/copy), `version` (head), `storage_class`
   (head). `setxattr` for `content_type` via `copy_object` with
   `MetadataDirective=REPLACE`.
4. **`src/asya-state-proxy/asya_state_proxy/connectors/s3_buffered_cas/connector.py`**
   — Same as above on `S3BufferedCAS`. CAS connector already tracks ETags internally
   — `getxattr("etag")` can return cached ETag from `self._etags[key]` when available,
   falling back to `head_object`.
5. **`src/asya-state-proxy/asya_state_proxy/connectors/s3_buffered_lww/connector.py`**
   — Same as above on `S3BufferedLWW`.

   Note: The three S3 connectors share identical xattr logic. Extract a mixin
   `_S3XattrMixin` to avoid duplication:
   ```python
   class _S3XattrMixin:
       _ATTRS = ["url", "presigned_url", "etag", "content_type", "version",
                 "storage_class"]
       _WRITABLE = {"content_type"}

       def listxattr(self, key): ...
       def getxattr(self, key, attr): ...
       def setxattr(self, key, attr, value): ...
   ```
   Place in `src/asya-state-proxy/asya_state_proxy/connectors/_s3_xattr.py` (or
   inline in each if mixin feels over-engineered for 3 files).

### Phase 3: Redis Connector

6. **`src/asya-state-proxy/asya_state_proxy/connectors/redis_buffered_cas/connector.py`**
   — Override `listxattr` → `["ttl"]`. `getxattr("ttl")` → `self._redis.ttl(key)`.
   `setxattr("ttl", value)` → `self._redis.expire(key, int(value))`.
   All other attrs → `KeyError`.

### Phase 4: Runtime

7. **`src/asya-runtime/asya_runtime.py`** — Patch `os.getxattr`, `os.listxattr`,
   `os.setxattr` inside `_install_state_proxy_hooks`. Intercept `user.asya.*`
   attributes on state mount paths, translate to HTTP on `/meta/` endpoints. Fall
   through to native for non-state paths and non-`user.asya.*` attributes.

### Phase 5: Testing Fixtures

8. **`src/asya-testing/`** — Add pytest fixture `mock_state_xattr` that patches
   `os.getxattr` (returns `file://` URIs for `user.asya.url`), `os.listxattr`
   (returns `["user.asya.url"]`), `os.setxattr` (no-op). Defines the functions on
   Windows where they don't exist.

### Phase 6: Tests

9. **`src/asya-state-proxy/tests/test_interface.py`** — Default `listxattr` returns
   `[]`, default `getxattr`/`setxattr` raise `KeyError`.
10. **`src/asya-state-proxy/tests/test_s3_passthrough.py`** — Add xattr tests.
11. **`src/asya-state-proxy/tests/test_s3_buffered_cas.py`** — Add xattr tests,
    verify cached ETag reuse.
12. **`src/asya-state-proxy/tests/test_s3_buffered_lww.py`** — Add xattr tests.
13. **`src/asya-state-proxy/tests/test_redis_buffered_cas.py`** — TTL xattr tests.
14. **`src/asya-state-proxy/tests/test_server.py`** — `/meta/` endpoint tests
    (list, get, set, error codes 400/403/404).
15. **`src/asya-runtime/tests/test_state_proxy.py`** — Patched `os.getxattr`,
    `os.listxattr`, `os.setxattr` tests (interception, passthrough, non-mount).
16. **`testing/component/state-proxy/tests/`** — Add xattr round-trip test:
    write → listxattr → getxattr → setxattr with MinIO.

### Phase 7: Documentation

17. Update state proxy RFC (1dmf) — done, see "Extended Attributes" section.
18. Update `docs/architecture/asya-state-proxy.md` with xattr usage examples.

## Testing Strategy

**Unit (connector)**:
- `listxattr("media/report.pdf")` → `["url", "presigned_url", "etag", ...]`
- `getxattr("media/report.pdf", "url")` → `"s3://bucket/prefix/media/report.pdf"`
- `getxattr("media/report.pdf", "etag")` → HEAD response ETag
- `getxattr("media/report.pdf", "unsupported")` → `KeyError`
- `setxattr("k", "content_type", "image/png")` → S3 CopyObject
- `setxattr("k", "url", "x")` → `PermissionError` (read-only)
- Redis: `listxattr` → `["ttl"]`, `getxattr("k", "url")` → `KeyError`

**Unit (server)**:
- `GET /meta/key` → `{"attrs": [...]}`
- `GET /meta/key?attr=url` → `{"attr": "url", "value": "s3://..."}`
- `GET /meta/key?attr=bad` → 400
- `PUT /meta/key?attr=url` → 403 (read-only)
- `PUT /meta/key?attr=content_type` → 204

**Unit (runtime)**:
- Patched `os.listxattr(path)` → returns `["user.asya.url", ...]`
- Patched `os.getxattr(path, "user.asya.url")` → returns bytes
- Patched `os.setxattr(path, "user.asya.content_type", b"...")` → 204
- Non-`user.asya.*` attributes → fall through to native
- Non-state-mount paths → fall through to native

**Component**: Docker Compose with MinIO — write file, listxattr, getxattr,
setxattr round-trip.

**asya-testing fixture**: `os.listxattr` → `["user.asya.url"]`,
`os.getxattr` → `file://` URIs, `os.setxattr` → no-op.
