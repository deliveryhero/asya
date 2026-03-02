---
title: "Implement functionality for actors to read stored artifact URL"
priority: 1
type: task
dependencies: []
tags: [state-proxy, a2a, artifacts]
---

## Motivation

Actors that produce files (PDFs, images, model outputs) need to reference them in
A2A artifacts. Today an actor can `open("/state/media/report.pdf", "wb")` and write
content — but has no way to obtain the external URL for that file to embed in
`payload.a2a.task.artifacts[].parts[].url`.

The actor doesn't (and shouldn't) know the storage backend configuration (bucket
name, prefix, region, endpoint). The state proxy connector owns all that. We need
a way for actors to ask: "what is the externally-addressable URL for this key?"

**Cross-reference**: A2A RFC (1c0d) Section 5.3.1 "State Proxy URL Extension".

## Current Architecture (Context)

```
Handler code  ──open("/state/media/k","w")──>  asya_runtime.py  ──PUT /keys/k──>  connector  ──>  S3
                                                (builtins patch)    (Unix socket)     (sidecar)
```

- **Runtime** (`asya_runtime.py`): Patches `builtins.open`, `os.stat`, `os.listdir`,
  `os.unlink`, `os.makedirs`. Translates to HTTP over Unix socket.
- **Connector interface** (`StateProxyConnector`): 6 methods — `read`, `write`,
  `exists`, `stat`, `list`, `delete`. None return URLs.
- **HTTP server** (`server.py`): Routes `GET/PUT/HEAD/DELETE /keys/{key}` and
  `GET /keys/?prefix=&delimiter=/`. PUT returns `204` with no body/headers.
- **S3 connectors**: Have `self._bucket`, `self._prefix`, `self._s3` internally.
  Can trivially compute `s3://{bucket}/{prefix}/{key}` or generate presigned URLs
  via `self._s3.generate_presigned_url(...)`.
- **Redis connector**: No URL-addressable objects. `external_url()` would raise
  `NotImplementedError` or return `None`.

## Constraint: No Custom Imports

`asya_runtime.py` is a ConfigMap-injected script — NOT a pip package. Handler code
cannot `from asya_runtime import anything`. The handler API surface is **stdlib only**:
whatever the runtime patches into `builtins` or `os` modules.

The existing pattern: runtime patches `builtins.open`, `os.stat`, `os.listdir`,
`os.unlink`, `os.makedirs`. Actors use these stdlib calls transparently. URL
resolution MUST follow the same pattern — a stdlib call that the runtime intercepts.

## Design

### Handler API: `os.getxattr`

```python
# Write a file (existing pattern — intercepted open())
with open("/state/media/report.pdf", "wb") as f:
    f.write(pdf_content)

# Get its external URL (new — intercepted os.getxattr())
url = os.getxattr("/state/media/report.pdf", "user.url")
# Returns: b"s3://my-bucket/prefix/media/report.pdf"
```

**Why `os.getxattr`**: Extended attributes are THE filesystem mechanism for attaching
metadata to files. "What is this file's external URL?" is metadata about a file —
exactly what xattrs are for. The `user.*` namespace is available to unprivileged
processes on Linux (no root/capabilities needed).

**Signature**: `os.getxattr(path, attribute, *, follow_symlinks=True) -> bytes`

**Platform availability**:
- Linux: available (native syscall)
- macOS: available (native syscall, Darwin 8.0+)
- Windows: NOT available (`AttributeError` on `os.getxattr`)

### URL Types

| Type | Example | Pros | Cons |
|------|---------|------|------|
| **S3 URI** | `s3://bucket/prefix/key` | Simple, stable, no expiry | Requires S3 access to consume |
| **HTTPS URL** | `https://bucket.s3.region.amazonaws.com/prefix/key` | Standard HTTP | Requires public access or signing |
| **Presigned URL** | `https://...?X-Amz-Signature=...` | Self-contained, no creds | Expires, long, single-use risk |

**Decision**: Return the **canonical backend URL** (S3 URI for S3 connectors). The
consumer (gateway, materializer, A2A client) resolves/proxies/presigns as needed.
Keeps connectors simple and avoids expiration concerns. Presigned URL generation is
the gateway's job when serving `GetTask(includeArtifacts=true)`.

### Cross-Platform Story

**K8s runtime (Linux)** — full support:
- Runtime patches `os.getxattr` for state mount paths
- `os.getxattr("/state/media/k", "user.url")` → HTTP to connector → S3 URI
- Non-state paths fall through to native `os.getxattr`

**Local dev (Linux/macOS)** — graceful degradation:
- `os.getxattr` exists natively on both platforms
- No state proxy running → calling on a real file raises `OSError` (ENODATA — no
  such attribute). This is expected — local files don't have external URLs.
- Actors that produce artifacts should guard the call:
  ```python
  try:
      url = os.getxattr("/state/media/report.pdf", "user.url").decode()
  except OSError:
      url = None  # URL resolution not available locally
  ```
- Alternatively, `asya-testing` provides a pytest fixture that patches
  `os.getxattr` to return `file://` URIs for local dev simulation.

**Local dev (Windows)** — `os.getxattr` doesn't exist:
- `AttributeError` on `os.getxattr`. Handler code should guard with
  `hasattr(os, "getxattr")` or catch both `AttributeError` and `OSError`.
- Windows is the minority case — most local dev happens on Linux/macOS.
- If needed, `asya-testing` fixture defines `os.getxattr` on Windows too.

**Comparison with existing pattern**: `open("/state/media/k")` "just works" locally
because real FS is the natural fallback. URL resolution has NO natural local
fallback — there IS no S3 URL for a local file. The try/except is inherent to the
feature, not a design flaw. This is infrastructure metadata, not data access.

### Layer Changes

#### 1. Connector Interface (`interface.py`)

Add a non-abstract `external_url` method with a default raise:

```python
class StateProxyConnector(ABC):
    # ... existing 6 methods ...

    def external_url(self, key: str) -> str:
        """Return the external URL for a stored key.

        Raises NotImplementedError for backends without URL-addressable
        objects (e.g., Redis).
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support external URLs"
        )
```

Not `@abstractmethod` — connectors that can't provide URLs (Redis, NATS KV) inherit
the default raise. Only URL-addressable backends override.

#### 2. S3 Connectors (all three)

Override `external_url` to return the S3 URI:

```python
def external_url(self, key: str) -> str:
    full_key = self._full_key(key)
    return f"s3://{self._bucket}/{full_key}"
```

No S3 API call needed — just concatenates known values.

#### 3. HTTP Server (`server.py`)

Add a new route: `GET /url/{key}` → JSON response with URL.

```
GET /url/media/report.pdf HTTP/1.1

HTTP/1.1 200 OK
Content-Type: application/json

{"url": "s3://my-bucket/prefix/media/report.pdf"}
```

Error responses:
- `501 Not Implemented` — connector doesn't support URLs (Redis)
- Standard error mapping for other failures

No existence check — URL is computed from key, not fetched from storage. The actor
just wrote the file; it should exist.

**Alternatives rejected**:
- `X-External-URL` header on PUT response — adds overhead to every write, forces
  runtime to cache. URL resolution is rare; should be on-demand.
- Query param on HEAD (`HEAD /keys/{key}?url=true`) — HEAD responses shouldn't
  have bodies; stuffing URLs into headers is awkward.

#### 4. Runtime (`asya_runtime.py`)

Patch `os.getxattr` inside `_install_state_proxy_hooks`, alongside the existing
`builtins.open`, `os.stat`, etc. patches:

```python
def _install_state_proxy_hooks(mounts_str):
    # ... existing patches ...

    _original_getxattr = getattr(os, "getxattr", None)

    def _patched_getxattr(path, attribute, *args, **kwargs):
        # Only intercept user.url on state mount paths
        attr_str = attribute.decode() if isinstance(attribute, bytes) else attribute
        if attr_str == "user.url":
            mount, key = _resolve_mount(path, mounts)
            if mount is not None:
                conn = _UnixHTTPClient(mount["socket"])
                conn.request("GET", f"/url/{key}")
                resp = conn.getresponse()
                if resp.status == 501:
                    raise OSError(errno.ENOTSUP, "Connector does not support URLs")
                _raise_for_status(resp, key)
                body = json.loads(resp.read())
                conn.close()
                return body["url"].encode("utf-8")

        # Fall through to original for non-state paths or other attributes
        if _original_getxattr is not None:
            return _original_getxattr(path, attribute, *args, **kwargs)
        raise OSError(errno.ENOTSUP, "Extended attributes not supported")

    os.getxattr = _patched_getxattr
```

Key design points:
- Returns `bytes` (matching real `os.getxattr` signature)
- Only intercepts `"user.url"` attribute — all other xattr calls pass through
- Non-state-mount paths fall through to native `os.getxattr`
- On platforms where `os.getxattr` doesn't exist (shouldn't happen on K8s/Linux),
  defines it as a function that raises `OSError(ENOTSUP)` for non-state paths
- Connector 501 → `OSError(ENOTSUP)` — maps HTTP error to appropriate errno

### Rejected Alternatives

#### `from asya_runtime import state_url`

Impossible. `asya_runtime.py` is ConfigMap-injected, not a pip package. Handler
code has no way to import from it.

#### `builtins.state_url` (magic builtin injection)

Runtime could inject `state_url` into `builtins`. But:
1. Non-standard builtin — developers wouldn't discover it without docs
2. Locally, `state_url` is undefined → `NameError` (worse than `OSError`)
3. Violates principle: patched calls should be EXISTING stdlib functions

#### `os.readlink` (virtual symlink resolution)

`os.readlink("/state/media/report.pdf")` → "where does this point?" → S3 URL.
Semantically appealing (state mounts ARE "links" to external storage). Cross-platform
(`os.readlink` exists on Linux, macOS, Windows). BUT:
1. `os.path.realpath()` calls `os.readlink()` internally — patching breaks it
2. Code that uses `readlink` result as a filesystem path gets a URL string
3. Conflicts with actual symlinks under state mounts

#### ABI Yield Protocol

`url = yield "GET", ".state.url(/state/media/report.pdf)"` — overloads ABI semantics
(message metadata, not storage), only works in generator handlers, awkward path syntax.

## Implementation Plan

1. Add `external_url(key) -> str` to `StateProxyConnector` (non-abstract, raises)
2. Override in `S3Passthrough`, `S3BufferedCAS`, `S3BufferedLWW`
3. Add `GET /url/{key}` route to `server.py`
4. Patch `os.getxattr` in `_install_state_proxy_hooks` in `asya_runtime.py`
5. Add `asya-testing` fixture for local dev xattr simulation
6. Unit tests: connector `external_url`, server `/url/` endpoint, runtime patching
7. Component test: runtime ↔ connector round-trip via `os.getxattr`

## Testing Strategy

- **Unit (connector)**: `S3Passthrough.external_url("media/report.pdf")` returns
  `"s3://bucket/prefix/media/report.pdf"`
- **Unit (server)**: `GET /url/media/report.pdf` → `{"url": "s3://..."}`
- **Unit (server, 501)**: Redis connector → `GET /url/key` → 501
- **Unit (runtime)**: Patched `os.getxattr(path, "user.url")` → calls connector,
  returns bytes
- **Unit (runtime, passthrough)**: `os.getxattr(path, "user.other")` → falls through
  to native or raises `OSError`
- **Unit (runtime, non-mount)**: `os.getxattr("/tmp/file", "user.url")` → native
  `os.getxattr` (no interception)
- **Component**: Docker Compose with MinIO — write file, `os.getxattr` → S3 URI
- **asya-testing fixture**: Verify `os.getxattr` returns `file://` URIs locally

## Open Questions

1. **Should URL computation verify key existence?** Recommendation: NO. S3 URIs are
   computed from bucket+prefix+key without an API call. The actor just wrote the file.
   Adding `exists()` would be an extra round-trip with no benefit.

2. **Presigned URL support (future)**: Defer to gateway. The gateway has S3 access
   and can `generate_presigned_url()` from the S3 URI when serving
   `GetTask(includeArtifacts=true)`. If actors need presigning directly, add
   `user.presigned_url` xattr with a separate connector method later.

3. **Redis/NATS KV connectors**: `external_url()` raises `NotImplementedError` →
   server returns 501 → runtime raises `OSError(ENOTSUP)`. Document that
   `os.getxattr(..., "user.url")` only works with URL-addressable backends.

4. **Windows local dev**: Provide `asya-testing` pytest fixture that defines
   `os.getxattr` on Windows and returns `file://` URIs. Not a blocker — Windows
   is minority for container-targeted dev.
