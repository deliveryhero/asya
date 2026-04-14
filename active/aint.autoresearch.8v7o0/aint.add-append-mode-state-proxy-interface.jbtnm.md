---
title: Add append mode to state proxy interface
status: open
priority: 1 # high
tags: [autoresearch, state-proxy]
---

## Context

State proxy currently treats `open(path, "a")` identically to `open(path, "w")` — it
overwrites the entire object. This breaks tools that rely on append semantics:

- **TensorBoard** (`tf.summary.FileWriter`) — appends TFEvent records to a single file
- **CSV/JSONL loggers** — append rows to log files
- **DVC** — may append to cache index files

The runtime already routes `"a"` mode to `_open_write` (asya_runtime.py:1011), but
`_open_write` doesn't distinguish append from write. The connector interface has no
`append()` method, and the HTTP server has no append endpoint.

## Design

### 1. Connector Interface Change

Add `append(key, data)` to `StateProxyConnector` in `interface.py`:

```python
def append(self, key: str, data: BinaryIO) -> None:
    """Append data to an existing key. Creates the key if it doesn't exist.

    Default implementation: read + concatenate + write (correct but expensive).
    Connectors may override with native append where available.
    """
    try:
        existing = self.read(key).read()
    except FileNotFoundError:
        existing = b""
    new_data = existing + data.read()
    import io
    self.write(key, io.BytesIO(new_data), size=len(new_data))
```

This is a non-abstract method with a default read-concat-write implementation.
Backends override where they have native support:

- **Redis**: `APPEND` command — O(1), native
- **S3**: no native append — use default (read + concat + write). For large files,
  consider S3 multipart upload with copy-part for the existing content.
- **GCS**: `compose()` — upload new chunk, compose with existing object

### 2. HTTP Server Change

Add `PATCH /keys/{key}` to `server.py`:

```
PATCH /keys/{key}
Body: raw bytes to append
Response: 204 No Content
```

PATCH is semantically correct (partial modification of a resource). The handler
reads the request body and calls `connector.append(key, data)`.

### 3. Runtime Change

In `asya_runtime.py`, create `_AppendWriteFile` class and update `_open_write`:

```python
class _AppendWriteFile:
    """Buffers writes locally, sends as PATCH on close."""
    def __init__(self, sock_path, key, text_mode):
        self._sock_path = sock_path
        self._key = key
        self._buf = io.BytesIO()
        self._text_mode = text_mode

    def write(self, data):
        if self._text_mode and isinstance(data, str):
            data = data.encode("utf-8")
        self._buf.write(data)
        return len(data)

    def close(self):
        self._buf.seek(0)
        body = self._buf.read()
        if body:
            conn = _UnixHTTPClient(self._sock_path)
            conn.request("PATCH", f"/keys/{self._key}",
                        body=body,
                        headers={"Content-Length": str(len(body))})
            resp = conn.getresponse()
            _raise_for_status(resp, self._key)
            conn.close()

    # __enter__/__exit__/flush/etc same as _BufferedWriteFile
```

Update `_patched_open` to distinguish "a" from "w":

```python
if "a" in mode:
    return _AppendWriteFile(mount["socket"], key, text_mode)
if "w" in mode:
    return _open_write(mount["socket"], key, mount["write_mode"], text_mode)
```

### 4. Buffered Mode Optimization

In buffered write mode, the sidecar already holds file contents in memory.
For append in buffered mode, the sidecar can accumulate appends locally and
flush the complete file on:

- Explicit `fsync()` / `close()`
- Periodic timer (configurable, default 5s)
- Sidecar shutdown (SIGTERM)

This makes high-frequency appends (like per-step TFEvents) cheap — only the
final flush hits S3.

## Scope

### In scope
- `append()` method on `StateProxyConnector` with default read+concat+write
- Redis connector: native `APPEND` override
- S3 connector: default implementation (read+concat+write) is fine for v1
- `PATCH /keys/{key}` HTTP endpoint on server
- `_AppendWriteFile` in runtime
- `_patched_open` distinguishes "a" from "w"
- Unit tests for all three layers

### Out of scope (follow-up)
- GCS connector `compose()` optimization
- S3 multipart-copy optimization for large files
- Buffered-mode append coalescing (sidecar-level)
- `open(path, "r+")` / `open(path, "a+")` (read+write modes)

## Testing

- Unit: mock connector, verify append creates new key and appends to existing
- Unit: runtime `_AppendWriteFile` buffers and sends PATCH
- Unit: server routes PATCH to `connector.append()`
- Component: S3 connector read+concat+write roundtrip
- Component: Redis connector native APPEND roundtrip
- Component: TFEvent writer on state proxy mount produces valid TFEvents file
