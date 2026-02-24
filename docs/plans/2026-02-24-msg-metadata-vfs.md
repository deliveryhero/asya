# Message Metadata Virtual Filesystem Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `ASYA_HANDLER_MODE=envelope` with a `/proc/asya/msg/` virtual filesystem so all handlers receive only payload and access metadata via standard `open()` calls.

**Architecture:** Patch `builtins.open` and `os.*` functions in the runtime to intercept `/proc/asya/msg/` paths. An in-memory `_MessageVFS` class backs reads/writes with zero disk I/O. Envelope mode is fully removed; all handlers (including crew actors) become payload-only handlers that use VFS for metadata access.

**Tech Stack:** Pure Python 3.7+ (no dependencies), `builtins.open` monkey-patching, `io.StringIO` for file-like objects.

**RFC:** `.aint/epics/1ixt.msg-metadata-vfs/rfc.md`

---

## Overview

### What changes

| Aspect | Before | After |
|--------|--------|-------|
| Handler mode | `ASYA_HANDLER_MODE=payload\|envelope` | Always payload (env var removed) |
| Handler input | payload dict OR full message | Always payload dict |
| Route access | Direct dict manipulation (envelope) | `open("/proc/asya/msg/route/next", "w")` |
| Header access | Direct dict manipulation (envelope) | `open("/proc/asya/msg/headers/{key}")` |
| Crew actors | Envelope mode + validation=false | Payload mode + VFS (validation works normally) |
| Flow routers | Envelope mode dict manipulation | Payload mode + VFS file writes |

### Task dependency graph

```
Task 1: Core VFS in asya_runtime.py
    │
    ├── Task 2: Migrate crew actors (sink.py, sump.py)
    ├── Task 3: Migrate test handlers (envelope.py, classes.py)
    ├── Task 4: Update flow compiler codegen
    ├── Task 5: Clean up config files
    │       │
    │       ├── Task 6: Update component tests
    │       └── Task 7: Update integration tests
    │
    └── Task 8: Update documentation
```

Tasks 2, 3, 4, 5 are independent of each other (can run in parallel after Task 1).
Tasks 6, 7 depend on Tasks 1-5 being complete.
Task 8 can run in parallel with Tasks 6-7.

---

## Task 1: Core VFS Implementation in asya_runtime.py

**Files:**
- Modify: `src/asya-runtime/asya_runtime.py`
- Test: `src/asya-runtime/tests/test_asya_runtime.py`

This is the core task. It adds the VFS, patches builtins, removes envelope mode,
and updates the frame collection logic. All other tasks depend on this.

### 1.1 VFS Filesystem Layout

```
/proc/asya/msg/                    # ASYA_MSG_ROOT (configurable)
├── id                             # read-only: message UUID
├── parent_id                      # read-only: parent UUID (empty if unset)
├── route/
│   ├── prev                       # read-only: actor_a\nactor_b
│   ├── curr                       # read-only: current_actor
│   └── next                       # read-write: next_actor_1\nnext_actor_2
├── headers/
│   ├── trace_id                   # read-write: trace-abc-123
│   └── priority                   # read-write: high
└── status/
    ├── phase                      # read-only: succeeded|failed
    └── {key}                      # read-only: arbitrary status fields
```

### 1.2 Implementation: _MessageVFS class

Add AFTER the `_error_response` function (around line 323). This class backs
the virtual filesystem with an in-memory dict.

```python
import builtins
import io

# --- Message Virtual Filesystem ---

ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")

# Read-only paths (handler cannot write to these)
_READ_ONLY_PATHS = frozenset({"id", "parent_id", "route/prev", "route/curr"})


class _MessageVFS:
    """In-memory virtual filesystem for message metadata.

    Populated before each handler invocation, read after handler returns.
    No disk I/O, no network - pure dict operations.
    """

    def __init__(self):
        self._data = {}
        self._active = False

    def populate(self, message):
        """Populate VFS from incoming message. Called before handler."""
        route = message["route"]
        self._data = {
            "id": message.get("id", ""),
            "parent_id": message.get("parent_id", ""),
            "route": {
                "prev": list(route["prev"]),
                "curr": route["curr"],
                "next": list(route["next"]),
            },
            "headers": dict(message.get("headers") or {}),
            "status": dict(message.get("status") or {}),
        }
        self._active = True

    def clear(self):
        """Clear VFS state. Called after handler completes."""
        self._data = {}
        self._active = False

    @property
    def active(self):
        return self._active

    def snapshot(self):
        """Snapshot mutable VFS state for frame construction.

        Returns current route.next and headers (both mutable by handler).
        Called at each generator yield and after handler return.
        """
        return {
            "route_next": list(self._data["route"]["next"]),
            "headers": dict(self._data["headers"]),
        }

    def read(self, rel_path):
        """Read a virtual file by relative path.

        Args:
            rel_path: Path relative to ASYA_MSG_ROOT (e.g., "id", "route/next")

        Returns:
            File content as string.

        Raises:
            FileNotFoundError: Path does not exist in VFS.
        """
        parts = rel_path.strip("/").split("/")

        if parts == ["id"]:
            return self._data.get("id", "")
        if parts == ["parent_id"]:
            return self._data.get("parent_id", "")
        if parts == ["route", "prev"]:
            return "\n".join(self._data["route"]["prev"])
        if parts == ["route", "curr"]:
            return self._data["route"]["curr"]
        if parts == ["route", "next"]:
            return "\n".join(self._data["route"]["next"])
        if len(parts) == 2 and parts[0] == "headers":
            key = parts[1]
            if key not in self._data["headers"]:
                raise FileNotFoundError(f"No such file: {ASYA_MSG_ROOT}/headers/{key}")
            return str(self._data["headers"][key])
        if len(parts) == 2 and parts[0] == "status":
            key = parts[1]
            if key not in self._data["status"]:
                raise FileNotFoundError(f"No such file: {ASYA_MSG_ROOT}/status/{key}")
            return str(self._data["status"][key])

        raise FileNotFoundError(f"No such file: {ASYA_MSG_ROOT}/{rel_path}")

    def write(self, rel_path, content):
        """Write to a virtual file.

        Args:
            rel_path: Path relative to ASYA_MSG_ROOT
            content: String content to write

        Raises:
            PermissionError: Path is read-only.
            FileNotFoundError: Path does not exist in VFS.
        """
        clean = rel_path.strip("/")
        if clean in _READ_ONLY_PATHS:
            raise PermissionError(f"Read-only: {ASYA_MSG_ROOT}/{clean}")
        if clean.startswith("status/") or clean == "status":
            raise PermissionError(f"Read-only: {ASYA_MSG_ROOT}/{clean}")

        parts = clean.split("/")
        if parts == ["route", "next"]:
            self._data["route"]["next"] = content.splitlines() if content else []
        elif len(parts) == 2 and parts[0] == "headers":
            self._data["headers"][parts[1]] = content
        else:
            raise FileNotFoundError(f"No such file: {ASYA_MSG_ROOT}/{clean}")

    def remove(self, rel_path):
        """Remove a virtual file (headers only).

        Raises:
            PermissionError: Path is read-only or not removable.
            FileNotFoundError: Header does not exist.
        """
        parts = rel_path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "headers":
            key = parts[1]
            if key not in self._data["headers"]:
                raise FileNotFoundError(f"No such file: {ASYA_MSG_ROOT}/headers/{key}")
            del self._data["headers"][key]
        elif parts == ["route", "next"]:
            # Deleting route/next = clearing it
            self._data["route"]["next"] = []
        else:
            raise PermissionError(f"Cannot remove: {ASYA_MSG_ROOT}/{rel_path}")

    def listdir(self, rel_path):
        """List directory contents.

        Raises:
            FileNotFoundError: Not a directory.
        """
        clean = rel_path.strip("/")
        if clean == "":
            entries = ["id", "route", "headers"]
            if self._data.get("parent_id"):
                entries.insert(1, "parent_id")
            if self._data.get("status"):
                entries.append("status")
            return entries
        if clean == "route":
            return ["prev", "curr", "next"]
        if clean == "headers":
            return list(self._data.get("headers", {}).keys())
        if clean == "status":
            return list(self._data.get("status", {}).keys())
        raise NotADirectoryError(f"Not a directory: {ASYA_MSG_ROOT}/{clean}")

    def exists(self, rel_path):
        """Check if a virtual path exists."""
        clean = rel_path.strip("/")
        if clean in ("", "route", "headers", "status"):
            return True
        if clean in ("id", "parent_id", "route/prev", "route/curr", "route/next"):
            return True
        parts = clean.split("/")
        if len(parts) == 2 and parts[0] == "headers":
            return parts[1] in self._data.get("headers", {})
        if len(parts) == 2 and parts[0] == "status":
            return parts[1] in self._data.get("status", {})
        return False

    def isdir(self, rel_path):
        """Check if a virtual path is a directory."""
        clean = rel_path.strip("/")
        return clean in ("", "route", "headers", "status")
```

### 1.3 Implementation: _MsgVirtualFile class

File-like object returned by patched `open()` for VFS paths.

```python
class _MsgVirtualFile:
    """File-like object backed by _MessageVFS.

    Supports with-statement (context manager), read(), write(), close().
    Uses io.StringIO for buffering. Flushes writes to VFS on close.
    """

    def __init__(self, vfs, rel_path, mode):
        self._vfs = vfs
        self._rel_path = rel_path
        self._mode = mode
        self._closed = False

        if "w" in mode:
            self._buffer = io.StringIO()
        else:
            content = vfs.read(rel_path)
            self._buffer = io.StringIO(content)

    def read(self, size=-1):
        if self._closed:
            raise ValueError("I/O operation on closed file")
        if size == -1:
            return self._buffer.read()
        return self._buffer.read(size)

    def readline(self):
        if self._closed:
            raise ValueError("I/O operation on closed file")
        return self._buffer.readline()

    def readlines(self):
        if self._closed:
            raise ValueError("I/O operation on closed file")
        return self._buffer.readlines()

    def write(self, data):
        if self._closed:
            raise ValueError("I/O operation on closed file")
        if "w" not in self._mode and "a" not in self._mode:
            raise io.UnsupportedOperation("not writable")
        return self._buffer.write(data)

    def close(self):
        if not self._closed:
            if "w" in self._mode or "a" in self._mode:
                self._vfs.write(self._rel_path, self._buffer.getvalue())
            self._buffer.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __iter__(self):
        return iter(self._buffer)

    @property
    def closed(self):
        return self._closed

    @property
    def name(self):
        return f"{ASYA_MSG_ROOT}/{self._rel_path}"
```

### 1.4 Implementation: Builtins patching

```python
# Globals for patching
_msg_vfs = _MessageVFS()
_original_open = None
_original_listdir = None
_original_path_exists = None
_original_path_isdir = None
_original_remove = None


def _patched_open(path, mode="r", *args, **kwargs):
    """Intercept open() for /proc/asya/msg/ paths."""
    path_str = os.fspath(path) if not isinstance(path, str) else path
    if _msg_vfs.active and path_str.startswith(ASYA_MSG_ROOT):
        rel = path_str[len(ASYA_MSG_ROOT):]
        if not rel:
            raise IsADirectoryError(f"Is a directory: '{path_str}'")
        return _MsgVirtualFile(_msg_vfs, rel, mode)
    return _original_open(path, mode, *args, **kwargs)


def _patched_listdir(path="."):
    path_str = os.fspath(path) if not isinstance(path, str) else path
    if _msg_vfs.active and path_str.startswith(ASYA_MSG_ROOT):
        rel = path_str[len(ASYA_MSG_ROOT):]
        return _msg_vfs.listdir(rel)
    return _original_listdir(path)


def _patched_path_exists(path):
    path_str = os.fspath(path) if not isinstance(path, str) else path
    if _msg_vfs.active and path_str.startswith(ASYA_MSG_ROOT):
        rel = path_str[len(ASYA_MSG_ROOT):]
        return _msg_vfs.exists(rel)
    return _original_path_exists(path)


def _patched_path_isdir(path):
    path_str = os.fspath(path) if not isinstance(path, str) else path
    if _msg_vfs.active and path_str.startswith(ASYA_MSG_ROOT):
        rel = path_str[len(ASYA_MSG_ROOT):]
        return _msg_vfs.isdir(rel)
    return _original_path_isdir(path)


def _patched_remove(path):
    path_str = os.fspath(path) if not isinstance(path, str) else path
    if _msg_vfs.active and path_str.startswith(ASYA_MSG_ROOT):
        rel = path_str[len(ASYA_MSG_ROOT):]
        return _msg_vfs.remove(rel)
    return _original_remove(path)


def _install_msg_hooks():
    """Patch builtins.open and os.* to intercept /proc/asya/msg/ paths.

    Called once at runtime startup. Safe to call multiple times (idempotent).
    """
    global _original_open, _original_listdir
    global _original_path_exists, _original_path_isdir, _original_remove

    if _original_open is not None:
        return  # Already installed

    _original_open = builtins.open
    _original_listdir = os.listdir
    _original_path_exists = os.path.exists
    _original_path_isdir = os.path.isdir
    _original_remove = os.remove

    builtins.open = _patched_open
    io.open = _patched_open  # pathlib.Path uses io.open internally
    os.listdir = _patched_listdir
    os.path.exists = _patched_path_exists
    os.path.isdir = _patched_path_isdir
    os.remove = _patched_remove

    logger.info(f"Message VFS hooks installed (root: {ASYA_MSG_ROOT})")
```

### 1.5 Remove envelope mode

**Remove these items:**
- Line 75: `ASYA_HANDLER_MODE` variable
- Line 85: `VALID_ASYA_HANDLER_MODES` constant
- Line 134-135: Mode validation in `_load_function()`
- Lines 262-276: Envelope-specific validation in `_validate_message()` (remove `input_route` parameter)
- Lines 355-360: Mode dispatch in `_handle_invoke()` (always use payload mode)
- Lines 406-456: `_shift_envelope_route()` and `_collect_envelope_frames()` (delete entirely)
- Lines 514-523: Mode dispatch in `do_POST()` (always use payload mode)
- Line 553: Mode logging in `_log_env_vars()`

**Simplify `_validate_message()`:**
```python
def _validate_message(e):
    # type: (dict) -> dict
    """Validate incoming message structure. No output validation needed."""
    if "payload" not in e:
        raise ValueError("Missing required field 'payload' in message")
    if "route" not in e:
        raise ValueError("Missing required field 'route' in message")

    route = e["route"]
    if not isinstance(route, dict):
        raise ValueError("Field 'route' must be a dict")
    if "prev" not in route:
        raise ValueError("Missing required field 'prev' in route")
    if not isinstance(route["prev"], list):
        raise ValueError("Field 'route.prev' must be a list")
    if "curr" not in route:
        raise ValueError("Missing required field 'curr' in route")
    if not isinstance(route["curr"], str):
        raise ValueError("Field 'route.curr' must be a string")
    if "next" not in route:
        raise ValueError("Missing required field 'next' in route")
    if not isinstance(route["next"], list):
        raise ValueError("Field 'route.next' must be a list")

    if "headers" in e and not isinstance(e["headers"], dict):
        raise ValueError("Field 'headers' must be a dict")

    if "id" in e and not isinstance(e["id"], str):
        raise ValueError("Field 'id' must be a string")

    result = {"payload": e["payload"], "route": e["route"]}
    if "id" in e:
        result["id"] = e["id"]
    if "parent_id" in e:
        result["parent_id"] = e["parent_id"]
    if "headers" in e:
        result["headers"] = e["headers"]
    if "status" in e:
        result["status"] = e["status"]
    return result
```

### 1.6 Update frame collection to use VFS

Replace `_collect_payload_frames()` with VFS-aware version:

```python
def _collect_payload_frames(message, user_func):
    """Collect response frames using VFS for metadata.

    1. Populate VFS from message
    2. Call handler with payload only
    3. Snapshot VFS state (route.next, headers) for each frame
    4. Shift route and build frames
    5. Clear VFS
    """
    input_route = message["route"]
    status = message.get("status")

    # Populate VFS before handler
    _msg_vfs.populate(message)

    try:
        if inspect.isgeneratorfunction(user_func):
            frames = []
            for payload_value in user_func(message["payload"]):
                vfs_state = _msg_vfs.snapshot()
                frame = _build_frame(payload_value, input_route, vfs_state, status)
                frames.append(frame)
            return frames

        result = _call_handler(user_func, message["payload"])
        if result is None:
            return []

        vfs_state = _msg_vfs.snapshot()
        return [_build_frame(result, input_route, vfs_state, status)]
    finally:
        _msg_vfs.clear()


def _build_frame(payload_value, input_route, vfs_state, status):
    """Build a response frame with shifted route from VFS state.

    Args:
        payload_value: Handler return value (the payload)
        input_route: Original input route (for prev/curr)
        vfs_state: Snapshot of VFS mutable state (route_next, headers)
        status: Original status dict (preserved as-is)
    """
    prev = [*input_route["prev"], input_route["curr"]]
    handler_next = vfs_state["route_next"]

    if handler_next:
        route = {"prev": prev, "curr": handler_next[0], "next": handler_next[1:]}
    else:
        route = {"prev": prev, "curr": "", "next": []}

    frame = {"payload": payload_value, "route": route}
    if vfs_state["headers"]:
        frame["headers"] = vfs_state["headers"]
    if status is not None:
        frame["status"] = status
    return frame
```

### 1.7 Update _handle_invoke and do_POST

**`_handle_invoke()`** - remove mode dispatch:
```python
def _handle_invoke(data, user_func):
    try:
        message = _parse_message_json(data)
        if ASYA_ENABLE_VALIDATION:
            message = _validate_message(message)
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, ValueError) as exc:
        return 400, json.dumps(_error_response("msg_parsing_error", exc)).encode("utf-8")

    try:
        frames = _collect_payload_frames(message, user_func)
    except Exception as exc:
        return 500, json.dumps(_error_response("processing_error", exc)).encode("utf-8")

    if not frames:
        return 204, b""
    return 200, json.dumps({"frames": frames}).encode("utf-8")
```

**`do_POST()`** - remove mode dispatch:
```python
def do_POST(self):
    # ... (unchanged up to message parsing) ...

    try:
        user_func = self.server.user_func
        logger.info(
            f"[DIAG] Starting handler execution, "
            f"message_id={message.get('id', 'unknown')}"
        )
        frames = _collect_payload_frames(message, user_func)
    except Exception as exc:
        logger.exception("Fatal error on processing input message")
        self._send_json(500, _error_response("processing_error", exc))
        return

    # ... (unchanged response sending) ...
```

### 1.8 Update handle_requests

Add `_install_msg_hooks()` call and update logging:

```python
def handle_requests():
    """Main entry point, blocks forever."""
    _log_env_vars()
    _install_msg_hooks()  # Install VFS before loading handler

    func = _load_function()
    # ... rest unchanged ...
```

Update `_load_function()` to remove mode validation:
```python
def _load_function():
    # Remove: if ASYA_HANDLER_MODE not in VALID_ASYA_HANDLER_MODES ...
    if not ASYA_HANDLER:
        # ... rest unchanged ...
```

Update `_log_env_vars()`:
```python
def _log_env_vars():
    logger.info(
        f"Asya Actor Runtime starting with handler: '{ASYA_HANDLER}' "
        f"(msg_root: {ASYA_MSG_ROOT}, validation: {ASYA_ENABLE_VALIDATION})"
    )
    # ... rest unchanged ...
```

### 1.9 Update module docstring

Remove ASYA_HANDLER_MODE from docstring, add ASYA_MSG_ROOT:

```python
"""
...
Environment Variables:
    ASYA_HANDLER: Full path to function or method
    ASYA_MSG_ROOT: Root path for message virtual filesystem (default: "/proc/asya/msg")
    ASYA_SOCKET_CHMOD: Socket permissions in octal (default: "0o666")
    ASYA_ENABLE_VALIDATION: Enable message validation ("true" or "false", default: "true")
    ASYA_LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR, default: INFO)
...
"""
```

### 1.10 Unit tests for VFS

Add new test class in `test_asya_runtime.py`:

```python
class TestMessageVFS:
    """Tests for the /proc/asya/msg/ virtual filesystem."""

    def _make_message(self, **overrides):
        msg = {
            "id": "test-msg-001",
            "route": {"prev": ["actor_a"], "curr": "actor_b", "next": ["actor_c"]},
            "payload": {"text": "hello"},
            "headers": {"trace_id": "t123", "priority": "high"},
            "status": {"phase": "processing", "attempt": 1},
        }
        msg.update(overrides)
        return msg

    def test_read_scalar_fields(self, mock_env):
        """VFS reads id, parent_id, route/curr as plain text."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message(parent_id="parent-001"))
            assert vfs.read("id") == "test-msg-001"
            assert vfs.read("parent_id") == "parent-001"
            assert vfs.read("route/curr") == "actor_b"

    def test_read_list_fields(self, mock_env):
        """VFS reads route/prev and route/next as newline-separated lists."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message())
            assert vfs.read("route/prev") == "actor_a"
            assert vfs.read("route/next") == "actor_c"

    def test_read_headers(self, mock_env):
        """VFS reads individual header files."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message())
            assert vfs.read("headers/trace_id") == "t123"
            assert vfs.read("headers/priority") == "high"

    def test_read_status(self, mock_env):
        """VFS reads status fields as read-only."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message())
            assert vfs.read("status/phase") == "processing"

    def test_write_route_next(self, mock_env):
        """VFS allows writing to route/next."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message())
            vfs.write("route/next", "x\ny\nz")
            assert vfs.read("route/next") == "x\ny\nz"
            snap = vfs.snapshot()
            assert snap["route_next"] == ["x", "y", "z"]

    def test_write_headers(self, mock_env):
        """VFS allows writing to headers (create and update)."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message())
            vfs.write("headers/new_key", "new_value")
            assert vfs.read("headers/new_key") == "new_value"
            vfs.write("headers/priority", "low")
            assert vfs.read("headers/priority") == "low"

    def test_read_only_enforcement(self, mock_env):
        """VFS raises PermissionError for writes to read-only paths."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message())
            for path in ["id", "parent_id", "route/prev", "route/curr"]:
                with pytest.raises(PermissionError):
                    vfs.write(path, "new")
            with pytest.raises(PermissionError):
                vfs.write("status/phase", "new")

    def test_remove_header(self, mock_env):
        """VFS allows removing headers."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message())
            vfs.remove("headers/priority")
            with pytest.raises(FileNotFoundError):
                vfs.read("headers/priority")
            assert "priority" not in vfs.listdir("headers")

    def test_listdir(self, mock_env):
        """VFS listdir returns correct directory listings."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message())
            assert "trace_id" in vfs.listdir("headers")
            assert "priority" in vfs.listdir("headers")
            assert vfs.listdir("route") == ["prev", "curr", "next"]

    def test_snapshot_captures_mutable_state(self, mock_env):
        """Snapshot returns copies of route.next and headers."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message())
            snap1 = vfs.snapshot()
            vfs.write("route/next", "changed")
            snap2 = vfs.snapshot()
            assert snap1["route_next"] == ["actor_c"]
            assert snap2["route_next"] == ["changed"]

    def test_clear_resets_state(self, mock_env):
        """Clear makes VFS inactive and empty."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message())
            assert vfs.active
            vfs.clear()
            assert not vfs.active

    def test_file_not_found(self, mock_env):
        """VFS raises FileNotFoundError for nonexistent paths."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message())
            with pytest.raises(FileNotFoundError):
                vfs.read("nonexistent")
            with pytest.raises(FileNotFoundError):
                vfs.read("headers/nonexistent")

    def test_empty_route_next_write(self, mock_env):
        """Writing empty string to route/next clears the list."""
        with mock_env():
            from asya_runtime import _MessageVFS
            vfs = _MessageVFS()
            vfs.populate(self._make_message())
            vfs.write("route/next", "")
            assert vfs.snapshot()["route_next"] == []


class TestMsgVirtualFile:
    """Tests for the file-like object returned by patched open()."""

    def test_read_mode(self, mock_env):
        """MsgVirtualFile reads content correctly."""
        with mock_env():
            from asya_runtime import _MessageVFS, _MsgVirtualFile
            vfs = _MessageVFS()
            vfs.populate({"id": "test-001", "route": {"prev": [], "curr": "a", "next": ["b"]},
                          "payload": {}, "headers": {"key": "value"}})
            f = _MsgVirtualFile(vfs, "id", "r")
            assert f.read() == "test-001"
            f.close()

    def test_write_mode(self, mock_env):
        """MsgVirtualFile writes content on close."""
        with mock_env():
            from asya_runtime import _MessageVFS, _MsgVirtualFile
            vfs = _MessageVFS()
            vfs.populate({"id": "test-001", "route": {"prev": [], "curr": "a", "next": ["b"]},
                          "payload": {}, "headers": {}})
            f = _MsgVirtualFile(vfs, "route/next", "w")
            f.write("x\ny")
            f.close()
            assert vfs.snapshot()["route_next"] == ["x", "y"]

    def test_context_manager(self, mock_env):
        """MsgVirtualFile works as context manager."""
        with mock_env():
            from asya_runtime import _MessageVFS, _MsgVirtualFile
            vfs = _MessageVFS()
            vfs.populate({"id": "test-001", "route": {"prev": [], "curr": "a", "next": ["b"]},
                          "payload": {}, "headers": {"k": "v"}})
            with _MsgVirtualFile(vfs, "headers/k", "r") as f:
                assert f.read() == "v"

    def test_permission_error_on_read_only(self, mock_env):
        """MsgVirtualFile raises PermissionError for read-only paths in write mode."""
        with mock_env():
            from asya_runtime import _MessageVFS, _MsgVirtualFile
            vfs = _MessageVFS()
            vfs.populate({"id": "test-001", "route": {"prev": [], "curr": "a", "next": []},
                          "payload": {}})
            f = _MsgVirtualFile(vfs, "id", "w")
            f.write("new-id")
            with pytest.raises(PermissionError):
                f.close()


class TestBuiltinsPatching:
    """Tests for open() and os.* patching."""

    def test_patched_open_reads_vfs(self, mock_env):
        """Patched open() reads from VFS for /proc/asya/msg/ paths."""
        with mock_env(ASYA_MSG_ROOT="/tmp/test-msg"):
            import asya_runtime as rt
            rt._install_msg_hooks()
            rt._msg_vfs.populate({
                "id": "patched-test",
                "route": {"prev": [], "curr": "a", "next": ["b"]},
                "payload": {},
                "headers": {"key": "val"},
            })
            try:
                with open("/tmp/test-msg/id") as f:
                    assert f.read() == "patched-test"
                with open("/tmp/test-msg/headers/key") as f:
                    assert f.read() == "val"
            finally:
                rt._msg_vfs.clear()

    def test_patched_open_writes_vfs(self, mock_env):
        """Patched open() writes to VFS for /proc/asya/msg/ paths."""
        with mock_env(ASYA_MSG_ROOT="/tmp/test-msg"):
            import asya_runtime as rt
            rt._install_msg_hooks()
            rt._msg_vfs.populate({
                "id": "test",
                "route": {"prev": [], "curr": "a", "next": ["b"]},
                "payload": {},
            })
            try:
                with open("/tmp/test-msg/route/next", "w") as f:
                    f.write("x\ny")
                assert rt._msg_vfs.snapshot()["route_next"] == ["x", "y"]
            finally:
                rt._msg_vfs.clear()

    def test_patched_open_passthrough(self, mock_env, tmp_path):
        """Patched open() passes through for non-VFS paths."""
        with mock_env(ASYA_MSG_ROOT="/tmp/test-msg"):
            import asya_runtime as rt
            rt._install_msg_hooks()
            real_file = tmp_path / "real.txt"
            with open(str(real_file), "w") as f:
                f.write("real content")
            with open(str(real_file)) as f:
                assert f.read() == "real content"

    def test_patched_listdir(self, mock_env):
        """Patched os.listdir() works for VFS paths."""
        with mock_env(ASYA_MSG_ROOT="/tmp/test-msg"):
            import asya_runtime as rt
            rt._install_msg_hooks()
            rt._msg_vfs.populate({
                "id": "test",
                "route": {"prev": [], "curr": "a", "next": []},
                "payload": {},
                "headers": {"h1": "v1", "h2": "v2"},
            })
            try:
                result = os.listdir("/tmp/test-msg/headers")
                assert sorted(result) == ["h1", "h2"]
            finally:
                rt._msg_vfs.clear()

    def test_patched_remove(self, mock_env):
        """Patched os.remove() removes VFS headers."""
        with mock_env(ASYA_MSG_ROOT="/tmp/test-msg"):
            import asya_runtime as rt
            rt._install_msg_hooks()
            rt._msg_vfs.populate({
                "id": "test",
                "route": {"prev": [], "curr": "a", "next": []},
                "payload": {},
                "headers": {"to_delete": "value"},
            })
            try:
                os.remove("/tmp/test-msg/headers/to_delete")
                assert "to_delete" not in rt._msg_vfs.listdir("headers")
            finally:
                rt._msg_vfs.clear()
```

### 1.11 Update existing unit tests

Many existing tests use envelope mode. These need updating:

1. **Remove all `ASYA_HANDLER_MODE=envelope` test cases** from `test_asya_runtime.py`
2. **Convert envelope-mode tests to VFS tests** where they test dynamic routing:
   - Tests that modify `route.next` should use `open("/proc/asya/msg/route/next", "w")`
   - Tests that read headers should use `open("/proc/asya/msg/headers/...")`
3. **Update `mock_env` fixture** to accept `ASYA_MSG_ROOT` parameter
4. **Remove `VALID_ASYA_HANDLER_MODES` references** from validation tests

### 1.12 Verification

Run: `make -C src/asya-runtime test-unit`
Expected: All tests pass, no envelope mode references remain.

---

## Task 2: Migrate Crew Actors

**Files:**
- Modify: `src/asya-crew/asya_crew/sink.py`
- Modify: `src/asya-crew/asya_crew/sump.py`
- Test: `src/asya-crew/tests/` (if exists, otherwise unit tests embedded)

### 2.1 Migrate sink.py

The sink handler changes from envelope mode (receiving full message) to
payload mode with VFS access for metadata.

**Before:**
```python
ASYA_HANDLER_MODE = (os.getenv("ASYA_HANDLER_MODE") or "payload").lower()
if ASYA_HANDLER_MODE != "envelope":
    raise RuntimeError(...)
if ASYA_ENABLE_VALIDATION:
    raise RuntimeError(...)

def sink_handler(message: dict[str, Any]) -> dict[str, Any]:
    if "id" not in message:
        raise ValueError("Message missing required field: id")
    message_id = message["id"]
    has_fan_in = bool((message.get("headers") or {}).get("x-asya-fan-in"))
    has_parent_id = message.get("parent_id") is not None
    # ...
    if ASYA_SINK_HOOKS:
        message["route"] = {"prev": [], "curr": hooks[0], "next": hooks[1:]}
        return message
    return {}
```

**After:**
```python
# Remove: ASYA_HANDLER_MODE check
# Remove: ASYA_ENABLE_VALIDATION check

ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")

def sink_handler(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Sink handler. Receives payload, accesses metadata via /proc/asya/msg/."""
    with open(f"{ASYA_MSG_ROOT}/id") as f:
        message_id = f.read()

    # Read status
    try:
        with open(f"{ASYA_MSG_ROOT}/status/phase") as f:
            phase = f.read()
    except FileNotFoundError:
        phase = "unknown"

    # Check fan-in header
    try:
        with open(f"{ASYA_MSG_ROOT}/headers/x-asya-fan-in") as f:
            has_fan_in = bool(f.read())
    except FileNotFoundError:
        has_fan_in = False

    # Check parent_id
    with open(f"{ASYA_MSG_ROOT}/parent_id") as f:
        has_parent_id = bool(f.read())

    logger.info(
        f"Processing sink for message {message_id}, phase={phase}, "
        f"fan_in={has_fan_in}, parent_id={has_parent_id}"
    )

    # S3 persistence (if configured)
    if ASYA_S3_BUCKET:
        try:
            from asya_crew.message_persistence.s3 import checkpoint_handler
            checkpoint_handler(payload)  # TODO: may need full message reconstruction
        except Exception as e:
            logger.error(f"S3 persistence failed for message {message_id}: {e}")

    # Skip hooks for fire-and-forget fan-out children
    if has_parent_id and not has_fan_in and not ASYA_SINK_FANOUT_HOOKS:
        logger.info(f"Fan-out child (parent_id set), skipping hooks for message {message_id}")
        return payload

    if ASYA_SINK_HOOKS:
        hooks = [h.strip() for h in ASYA_SINK_HOOKS.split(",") if h.strip()]
        if hooks:
            logger.info(f"Routing message {message_id} to hooks: {hooks}")
            with open(f"{ASYA_MSG_ROOT}/route/next", "w") as f:
                f.write("\n".join(hooks))
            return payload

    logger.info(f"No hooks configured, message {message_id} passes through to sump")
    return payload
```

### 2.2 Migrate sump.py

**After:**
```python
# Remove: ASYA_HANDLER_MODE check
# Remove: ASYA_ENABLE_VALIDATION check

ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")

def sump_handler(payload: dict[str, Any]) -> None:
    """Sump handler. Terminal actor, logs and acknowledges."""
    with open(f"{ASYA_MSG_ROOT}/id") as f:
        message_id = f.read()

    try:
        with open(f"{ASYA_MSG_ROOT}/status/phase") as f:
            phase = f.read()
    except FileNotFoundError:
        phase = "unknown"

    if phase == "failed":
        # Reconstruct message for logging
        msg_info = {"id": message_id, "phase": phase, "payload": payload}
        logger.error(
            f"Terminal failure for message {message_id}: "
            f"{json.dumps(msg_info, indent=2, default=str)}"
        )
    elif phase == "succeeded":
        logger.debug(f"Terminal success for message {message_id}")
    else:
        logger.info(f"Terminal non-final phase '{phase}' for message {message_id}")

    if ASYA_S3_BUCKET:
        try:
            from asya_crew.message_persistence.s3 import checkpoint_handler
            checkpoint_handler(payload)
        except Exception as e:
            logger.error(f"S3 persistence failed for message {message_id}: {e}")

    return None
```

### 2.3 Verification

Run: `make -C src/asya-crew test-unit` (if exists)
Check: No references to ASYA_HANDLER_MODE remain in crew code.

---

## Task 3: Migrate Test Handlers

**Files:**
- Delete: `src/asya-testing/asya_testing/handlers/envelope.py`
- Modify: `src/asya-testing/asya_testing/handlers/classes.py`
- Modify: `src/asya-testing/asya_testing/handlers/__init__.py` (if it exports envelope)

### 3.1 Delete envelope.py

The entire `envelope.py` module is no longer needed. All handlers now receive
payload only. Delete the file.

### 3.2 Update classes.py

The `MessageHandler` class currently uses envelope mode. Migrate to VFS:

**Before:**
```python
class MessageHandler:
    def __init__(self):
        self.prefix = "processed"
        self.message_count = 0

    async def process(self, message: dict[str, Any]) -> dict[str, Any]:
        self.message_count += 1
        trace_id = message.get("headers", {}).get("trace_id", "unknown")
        return {
            "payload": {...},
            "route": message["route"],
            "headers": message.get("headers", {}),
        }
```

**After:**
```python
import os

ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")

class MessageHandler:
    """Handler that accesses message metadata via VFS."""

    def __init__(self):
        self.prefix = "processed"
        self.message_count = 0

    async def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.message_count += 1

        # Access trace_id via VFS
        try:
            with open(f"{ASYA_MSG_ROOT}/headers/trace_id") as f:
                trace_id = f.read()
        except FileNotFoundError:
            trace_id = "unknown"

        return {
            "prefix": self.prefix,
            "trace_id": trace_id,
            "data": payload,
            "message_count": self.message_count,
        }
```

### 3.3 Update __init__.py

Remove any exports of envelope module. Check if `__init__.py` references envelope.

### 3.4 Add VFS-aware test handlers

Add new handlers for testing VFS operations in
`src/asya-testing/asya_testing/handlers/payload.py`:

```python
ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")

def route_modifier_handler(payload):
    """Handler that modifies route.next via VFS."""
    with open(f"{ASYA_MSG_ROOT}/route/next", "w") as f:
        f.write("\n".join(["injected_actor", "final_actor"]))
    return payload

def header_reader_handler(payload):
    """Handler that reads headers via VFS."""
    try:
        with open(f"{ASYA_MSG_ROOT}/headers/trace_id") as f:
            trace_id = f.read()
    except FileNotFoundError:
        trace_id = "none"
    return {**payload, "trace_id": trace_id}

def metadata_inspector_handler(payload):
    """Handler that reads all metadata via VFS."""
    with open(f"{ASYA_MSG_ROOT}/id") as f:
        msg_id = f.read()
    with open(f"{ASYA_MSG_ROOT}/route/curr") as f:
        curr = f.read()
    headers = {}
    for key in os.listdir(f"{ASYA_MSG_ROOT}/headers"):
        with open(f"{ASYA_MSG_ROOT}/headers/{key}") as f:
            headers[key] = f.read()
    return {**payload, "meta": {"msg_id": msg_id, "actor": curr, "headers": headers}}
```

### 3.5 Verification

Run: `python -c "from asya_testing.handlers import payload"` (no import errors)
Check: No references to envelope mode remain in asya_testing.

---

## Task 4: Update Flow Compiler Codegen

**Files:**
- Modify: `src/asya-cli/asya_cli/flow/codegen.py`
- Modify: `src/asya-testing/asya_testing/flows/*/compiled/routers.py` (all compiled fixtures)
- Test: `src/asya-cli/tests/flow/test_codegen.py`

### 4.1 Update CodeGenerator

Generated routers currently use envelope mode (`message: dict → r = message['route']`).
Migrate to payload mode with VFS.

**Before (generated code pattern):**
```python
def start_my_flow(message: dict) -> dict:
    r = message['route']
    r['next'] = [resolve("handler_a")] + r['next']
    return message
```

**After (generated code pattern):**
```python
import os
ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")

def start_my_flow(payload: dict) -> dict:
    with open(f"{ASYA_MSG_ROOT}/route/next") as _f:
        _next = _f.read().splitlines()
    _next = [resolve("handler_a")] + _next
    with open(f"{ASYA_MSG_ROOT}/route/next", "w") as _f:
        _f.write("\n".join(_next))
    return payload
```

**For mutation routers:**
```python
def router_my_flow_line_3_seq(payload: dict) -> dict:
    with open(f"{ASYA_MSG_ROOT}/route/next") as _f:
        _next_tail = _f.read().splitlines()
    _next = []

    payload['status'] = 'processing'
    _next.append(resolve("handler_a"))
    _next.append(resolve("handler_b"))

    with open(f"{ASYA_MSG_ROOT}/route/next", "w") as _f:
        _f.write("\n".join(_next + _next_tail))
    return payload
```

**For conditional routers:**
```python
def router_my_flow_line_5_if(payload: dict) -> dict:
    with open(f"{ASYA_MSG_ROOT}/route/next") as _f:
        _next_tail = _f.read().splitlines()
    _next = []

    if payload['type'] == 'express':
        _next.append(resolve("express_handler"))
    else:
        _next.append(resolve("standard_handler"))

    with open(f"{ASYA_MSG_ROOT}/route/next", "w") as _f:
        _f.write("\n".join(_next + _next_tail))
    return payload
```

### 4.2 Update code generation methods in CodeGenerator class

Modify these methods in `codegen.py`:
- `_generate_preamble()`: Add `import os` and `ASYA_MSG_ROOT` constant
- `_generate_start_router()`: Use VFS instead of `r = message['route']`
- `_generate_router()`: Use VFS for route manipulation
- `_generate_end_router()`: Use VFS
- `_generate_loop_back_router()`: Use VFS
- `_generate_try_enter_router()`: Use VFS
- `_generate_try_exit_router()`: Use VFS
- `_generate_except_dispatch_router()`: Use VFS
- `_generate_reraise_router()`: Use VFS

**Key pattern change:**
- Old: `r = message['route']` ... `r['next'] = _next + r['next']` ... `return message`
- New: Read `_next_tail` from VFS ... modify ... write back to VFS ... `return payload`

### 4.3 Regenerate compiled test fixtures

All compiled router fixtures in `src/asya-testing/asya_testing/flows/*/compiled/routers.py`
need to be regenerated with the new codegen. Run:

```bash
asya flow compile <flow>.py --output-dir compiled/ --overwrite
```

For each flow in `src/asya-testing/asya_testing/flows/`.

### 4.4 Update codegen tests

Update `src/asya-cli/tests/flow/test_codegen.py`:
- Change assertions from `message: dict` to `payload: dict`
- Change route assertions from `r['next'] = ...` to VFS file operations
- Update all `in code` assertions

### 4.5 Verification

Run: `make -C src/asya-cli test-unit`
Expected: All codegen tests pass with new VFS-based generated code.

---

## Task 5: Clean Up Config Files

**Files to modify:**

### 5.1 Makefiles (remove ASYA_HANDLER_MODE parametrization)

- `testing/component/runtime/Makefile`: Remove `ASYA_HANDLER_MODE` export and the
  `test-one ASYA_HANDLER_MODE=envelope` call. Tests now run once (no mode split).
- `testing/component/sidecar/Makefile`: Remove `ASYA_HANDLER_MODE` export.
- `testing/integration/sidecar-runtime/Makefile`: Remove envelope mode test runs.
  Tests now run once per transport (no mode split).
- `testing/integration/gateway-actors/Makefile`: Remove envelope mode test runs.

### 5.2 Environment files

Remove `ASYA_HANDLER_MODE` line from:
- `testing/shared/compose/envs/.env.asya-runtime`
- `testing/shared/compose/envs/.env.tester`
- `testing/component/sidecar/profiles/.env.shared`
- `testing/component/sidecar/profiles/.env.sqs`
- `testing/component/sidecar/profiles/.env.rabbitmq`
- `testing/component/gateway/profiles/.env.shared`
- `testing/component/gateway/profiles/.env.sqs`
- `testing/component/gateway/profiles/.env.rabbitmq`

### 5.3 Docker Compose files

Remove `ASYA_HANDLER_MODE` from environment sections:
- `testing/component/runtime/docker-compose.yml` (all services)
- `testing/shared/compose/asya/crew-actors.yml` (sink + sump: remove mode=envelope)
- `testing/integration/sidecar-runtime/compose/actors.yml` (all services)
- `testing/integration/gateway-actors/` compose files

Also remove `ASYA_ENABLE_VALIDATION=false` from crew actor services
(no longer needed with VFS).

Update handler references from `asya_testing.handlers.${ASYA_HANDLER_MODE}.echo_handler`
to `asya_testing.handlers.payload.echo_handler` (hardcoded, no mode variable).

### 5.4 Helm charts

- `deploy/helm-charts/asya-crew/templates/sink.yaml`: Remove ASYA_HANDLER_MODE
  and ASYA_ENABLE_VALIDATION env vars
- `deploy/helm-charts/asya-crew/templates/sump.yaml`: Same
- `deploy/helm-charts/asya-crew/templates/checkpoint-s3.yaml`: Same
- `deploy/helm-charts/asya-crew/values.yaml`: Remove handler mode docs
- `deploy/helm-charts/asya-actor/values.yaml`: Remove handler mode comment
- `deploy/helm-charts/asya-actor/examples/*.yaml`: Remove ASYA_HANDLER_MODE
- `deploy/helm-charts/asya-playground/templates/*.yaml`: Remove ASYA_HANDLER_MODE

### 5.5 E2E test charts

- `testing/e2e/charts/asya-test-actors/templates/actor-echo.yaml`: Remove handlerMode
- `testing/e2e/charts/asya-test-flows/templates/*.yaml`: Remove handlerMode
- `testing/e2e/charts/*/values.yaml`: Remove handlerMode value

### 5.6 Examples

- `examples/asyas/fully-configured-actor.yaml`: Remove ASYA_HANDLER_MODE

### 5.7 Verification

Run: `grep -r "ASYA_HANDLER_MODE" --include="*.yml" --include="*.yaml" --include="*.env" --include="Makefile" .`
Expected: No matches (all references removed).

---

## Task 6: Update Component Tests

**Files:**
- Modify: `testing/component/runtime/tests/` (all test files)
- Modify: `testing/component/runtime/docker-compose.yml`
- Modify: `testing/component/sidecar/` (if has envelope-specific tests)

### 6.1 Update runtime component tests

- Remove envelope-specific test cases
- Add VFS-based tests (route modification, header access)
- Update service references in docker-compose (remove `asya-envelope-class-runtime`)
- Remove `ASYA_HANDLER_MODE` from environment sections
- Add `ASYA_MSG_ROOT` if needed for test isolation

### 6.2 Add VFS component test service

Add a new test actor service for VFS testing:
```yaml
  asya-vfs-test-runtime:
    extends:
      file: ../../shared/compose/asya/testing-actors.yml
      service: asya-echo-runtime
    environment:
      ASYA_HANDLER: asya_testing.handlers.payload.route_modifier_handler
```

### 6.3 Verification

Run: `make -C testing/component/runtime test`
Expected: All component tests pass.

---

## Task 7: Update Integration Tests

**Files:**
- Modify: `testing/integration/sidecar-runtime/tests/test_sidecar_with_runtime.py`
- Modify: `testing/integration/sidecar-runtime/compose/actors.yml`
- Modify: `testing/integration/sidecar-runtime/Makefile`
- Modify: `testing/integration/gateway-actors/` (similar changes)

### 7.1 Update integration test suite

- Remove envelope mode parametrization from Makefile
- Remove `ASYA_HANDLER_MODE` from docker-compose actor definitions
- Convert envelope-specific test handlers to VFS handlers
- Update test assertions for VFS-based routing

### 7.2 Key test conversions

**`fail_once_envelope_handler`** → VFS version:
```python
def fail_once_handler(payload):
    """Fails on attempt 1, succeeds on attempt 2+.
    Reads attempt from status via VFS.
    """
    try:
        with open(f"{ASYA_MSG_ROOT}/status/attempt") as f:
            attempt = int(f.read())
    except (FileNotFoundError, ValueError):
        attempt = 1
    if attempt <= 1:
        raise ValueError("Intentional first-attempt failure (attempt 1)")
    return {**payload, "succeeded_on_attempt": attempt}
```

**`invalid_route_current_handler`** → This test is about violating read-only constraint.
With VFS, writing to `route/curr` raises `PermissionError` immediately, so the
test should verify the runtime returns a 500 error when a handler tries to write
to a read-only path.

### 7.3 Verification

Run: `make -C testing/integration/sidecar-runtime test`
Expected: All integration tests pass.

---

## Task 8: Update Documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/architecture/asya-runtime.md`
- Modify: `docs/architecture/protocols/sidecar-runtime.md`
- Modify: `docs/architecture/asya-flow.md` (if exists)

### 8.1 Update AGENTS.md

- Remove all references to `ASYA_HANDLER_MODE`
- Remove envelope mode handler examples
- Update handler documentation to show VFS usage
- Add `ASYA_MSG_ROOT` to environment variable docs
- Update crew actor documentation
- Add VFS section under runtime documentation

### 8.2 Update architecture docs

- `asya-runtime.md`: Add VFS section, remove envelope mode
- `sidecar-runtime.md`: Update protocol docs, remove mode field
- `asya-flow.md`: Update generated router examples

### 8.3 Verification

Visual review of documentation changes.

---

## Execution Strategy

This plan has 8 tasks. The recommended execution approach:

1. **Task 1** (core VFS): Must be first, largest task (~300 lines of new code)
2. **Tasks 2-5** (migrations + config): Run in parallel after Task 1
3. **Tasks 6-7** (test updates): Run after Tasks 2-5
4. **Task 8** (docs): Run in parallel with Tasks 6-7

Total estimated scope: ~2000 lines changed across ~60 files.
