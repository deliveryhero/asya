#!/usr/bin/env python3
"""
Asya Actor Runtime - Unix Socket Server
Supported Python versions: 3.7+

Simplified runtime that calls a user-specified Python function or class method.
Async handlers (async def) are transparently supported via asyncio.run().

Handler Types:
    Function handler (async preferred for AI workloads):
        async def process(payload: dict) -> dict:
            result = await llm.generate(payload["prompt"])
            return {"result": result}

    Sync function handler (still fully supported):
        def process(payload: dict) -> dict:
            return {"result": ...}

    Class handler: Stateful handler with initialization
        class Processor:
            def __init__(self, config: str = "/default/path"):
                self.model = load_model(config)  # Init once, always sync

            async def process(self, payload: dict) -> dict:
                return await self.model.predict(payload)

        Note: All __init__ parameters must have default values for zero-arg instantiation.
        Note: __init__ is always synchronous. Only the handler method can be async.

Environment Variables:
    ASYA_HANDLER: Full path to function or method (e.g., "foo.bar.process" or "foo.bar.Processor.process")
    ASYA_MSG_ROOT: Virtual filesystem root for message metadata (default: "/proc/asya/msg")
    ASYA_SOCKET_CHMOD: Socket permissions in octal (default: "0o666", empty = skip chmod)
    ASYA_ENABLE_VALIDATION: Enable message validation ("true" or "false", default: "true")
    ASYA_LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR, default: INFO)

Socket Configuration:
    The socket path defaults to /var/run/asya/asya-runtime.sock and is managed by the operator.
    ASYA_SOCKET_DIR and ASYA_SOCKET_NAME are for internal testing only - DO NOT set in production.
"""

import asyncio
import builtins
import contextlib
import copy
import errno
import http.client as _http_client
import http.server
import importlib
import inspect
import io
import json
import logging
import os
import re
import shutil
import signal
import socket
import stat as _stat_module
import sys
import tempfile as _tempfile
import traceback
from typing import Any


# Configure logging with unbuffered output
log_level = os.getenv("ASYA_LOG_LEVEL", "INFO").upper()
log_level_value = getattr(logging, log_level, logging.INFO)

# Ensure stderr is unbuffered
sys.stderr.reconfigure(line_buffering=True)

logging.basicConfig(
    level=log_level_value,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,  # Recreate root logger handlers
)
logger = logging.getLogger("asya.runtime")

# Configuration
ASYA_HANDLER = os.getenv("ASYA_HANDLER", "")
ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")
ASYA_SOCKET_CHMOD = os.getenv("ASYA_SOCKET_CHMOD", "0o666")
ASYA_ENABLE_VALIDATION = os.getenv("ASYA_ENABLE_VALIDATION", "true").lower() == "true"

# Socket configuration - hard-coded, managed by operator
# ASYA_SOCKET_DIR and ASYA_SOCKET_NAME are for internal testing only - DO NOT set in production
SOCKET_DIR = os.getenv("ASYA_SOCKET_DIR", "/var/run/asya")
SOCKET_NAME = os.getenv("ASYA_SOCKET_NAME", "asya-runtime.sock")
SOCKET_PATH = os.path.join(SOCKET_DIR, SOCKET_NAME)


def _instantiate_class_handler(handler_class):
    """Instantiate class handler.

    Args:
        handler_class: The class to instantiate

    Returns:
        Instance of the class

    Raises:
        TypeError: If __init__ has parameters without defaults
        RuntimeError: If instantiation fails
    """
    # Check if class defines its own __init__ (not inherited from object)
    has_custom_init = "__init__" in handler_class.__dict__

    if has_custom_init:
        # Validate constructor signature - all params must have defaults
        sig = inspect.signature(handler_class.__init__)
        params = [p for p in sig.parameters.values() if p.name != "self"]

        for param in params:
            if param.default is inspect.Parameter.empty:
                raise TypeError(
                    f"Class handler {handler_class.__name__}.__init__() "
                    f"parameter '{param.name}' must have a default value. "
                    f"All __init__ parameters must be optional for zero-arg instantiation."
                )

    # Instantiate with no arguments
    try:
        instance = handler_class()
        logger.info(f"Instantiated class handler: {handler_class.__name__}")
    except Exception as e:
        raise RuntimeError(f"Failed to instantiate {handler_class.__name__}: {e}") from e

    return instance


def _load_function():
    """Load the user function from ASYA_HANDLER env var.

    Supports two formats:
    - module.path.function -> direct function
    - module.path.Class.method -> class method (class is instantiated)
    """
    if not ASYA_HANDLER:
        logger.critical("FATAL: ASYA_HANDLER not set")
        sys.exit(1)

    # Validate ASYA_HANDLER format to prevent path traversal and injection attacks
    handler_pattern = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+$")
    if not handler_pattern.match(ASYA_HANDLER):
        logger.critical(
            f"FATAL: Invalid ASYA_HANDLER format: '{ASYA_HANDLER}' (not matching pattern {handler_pattern})"
        )
        logger.critical("Expected format: 'module.path.function' or 'module.path.Class.method'")
        sys.exit(1)

    # Split into parts and find module boundary by attempting imports
    parts = ASYA_HANDLER.split(".")
    if len(parts) < 2:
        logger.critical(f"FATAL: Invalid ASYA_HANDLER format: '{ASYA_HANDLER}' (parts: {parts})")
        logger.critical("Expected format: 'module.path.function' or 'module.path.Class.method'")
        sys.exit(1)

    # Try to find the module by attempting imports with progressively longer paths
    tried_modules = []
    module = None
    module_parts = []
    attr_parts = []

    for i in range(len(parts) - 1, 0, -1):
        module_path = ".".join(parts[:i])
        try:
            tried_modules.append(module_path)
            module = importlib.import_module(module_path)
            module_parts = parts[:i]
            attr_parts = parts[i:]
            break
        except ImportError:
            continue

    if module is None:
        logger.critical(f"FATAL: Could not import module from '{ASYA_HANDLER}' (no module found: {tried_modules})")
        logger.critical("Expected format: 'module.path.function' or 'module.path.Class.method'")
        sys.exit(1)

    try:
        # attr_parts should be either [function] or [Class, method]
        if len(attr_parts) == 1:
            # Direct function: module.function
            func_name = attr_parts[0]
            logger.info(f"Loading function handler: module={'.'.join(module_parts)} function={func_name}")
            handler = getattr(module, func_name)

            if not callable(handler):
                raise TypeError(f"{ASYA_HANDLER} is not callable")

            return handler

        elif len(attr_parts) == 2:
            # Class method: module.Class.method
            class_name, method_name = attr_parts
            logger.info(
                f"Loading class handler: module={'.'.join(module_parts)} class={class_name} method={method_name}"
            )

            handler_class = getattr(module, class_name)

            if not inspect.isclass(handler_class):
                raise TypeError(f"{class_name} is not a class")

            # Instantiate the class
            instance = _instantiate_class_handler(handler_class)

            # Get and validate the method
            if not hasattr(instance, method_name):
                raise AttributeError(f"Class {class_name} does not have method '{method_name}'")

            method = getattr(instance, method_name)
            if not callable(method):
                raise TypeError(f"{class_name}.{method_name} is not callable")

            return method

        else:
            raise ValueError(f"Invalid attribute path: {'.'.join(attr_parts)}. Expected 'function' or 'Class.method'")

    except Exception as e:
        logger.critical(f"Failed to load asya handler {ASYA_HANDLER}: {type(e).__name__}: {e}")
        logger.debug("Traceback:", exc_info=True)
        sys.exit(1)


def _parse_message_json(data: bytes) -> dict[str, Any]:
    """Parse received message from bytes to dict."""
    return json.loads(data.decode("utf-8"))


def _validate_message(
    e,  # type: dict
):
    # type: (...) -> dict
    if "payload" not in e:
        raise ValueError("Missing required field 'payload' in message")
    if "route" not in e:
        raise ValueError("Missing required field 'route' in message")

    # Validate route structure
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

    # Validate headers if present
    if "headers" in e and not isinstance(e["headers"], dict):
        raise ValueError("Field 'headers' must be a dict")

    # Validate id field if present
    if "id" in e and not isinstance(e["id"], str):
        raise ValueError("Field 'id' must be a string")

    result = {
        "payload": e["payload"],
        "route": e["route"],
    }
    if "id" in e:
        result["id"] = e["id"]
    if "parent_id" in e:
        result["parent_id"] = e["parent_id"]
    if "headers" in e:
        result["headers"] = e["headers"]
    if "status" in e:
        result["status"] = e["status"]

    return result


def _get_current_actor(message: dict) -> str:
    return message["route"]["curr"]


def _error_response(code: str, exc: Exception | None = None) -> dict[str, Any]:
    """Returns standardized error response frame."""
    error: dict[str, Any] = {"error": code}
    if exc is not None:
        exc_type = type(exc)

        def _fqn(cls: type) -> str:
            module = cls.__module__
            qualname = cls.__qualname__
            return f"{module}.{qualname}" if module != "builtins" else qualname

        fqn = _fqn(exc_type)
        mro = [_fqn(cls) for cls in exc_type.__mro__[1:] if cls not in (object, BaseException)]

        error["details"] = {
            "message": str(exc),
            "type": fqn,
            "mro": mro,
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }
    return error


# --- Message Virtual Filesystem ---

# Read-only paths (handler cannot write to these)
_READ_ONLY_PATHS = frozenset({"id", "parent_id", "route/prev", "route/curr"})


class _MessageVFS:
    """In-memory virtual filesystem for message metadata.

    Populated before each handler invocation, read after handler returns.
    No disk I/O, no network — pure dict operations.
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

        Returns current route.next, headers, and status (all mutable by handler).
        Called at each generator yield and after handler return.
        Uses deepcopy for status since it may contain nested dicts.
        """
        return {
            "route_next": list(self._data["route"]["next"]),
            "headers": dict(self._data["headers"]),
            "status": copy.deepcopy(self._data.get("status") or {}),
        }

    def read(self, rel_path):
        """Read a virtual file by relative path."""
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
        if parts[0] == "status" and len(parts) >= 2:
            node = self._data.get("status", {})
            for p in parts[1:]:
                if isinstance(node, dict) and p in node:
                    node = node[p]
                else:
                    raise FileNotFoundError(f"No such file: {ASYA_MSG_ROOT}/{rel_path}")
            if isinstance(node, dict):
                raise IsADirectoryError(f"Is a directory: {ASYA_MSG_ROOT}/{rel_path}")
            if isinstance(node, list):
                return "\n".join(str(x) for x in node)
            return str(node)

        raise FileNotFoundError(f"No such file: {ASYA_MSG_ROOT}/{rel_path}")

    def write(self, rel_path, content):
        """Write to a virtual file."""
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
        """Remove a virtual file or status subtree."""
        parts = rel_path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "headers":
            key = parts[1]
            if key not in self._data["headers"]:
                raise FileNotFoundError(f"No such file: {ASYA_MSG_ROOT}/headers/{key}")
            del self._data["headers"][key]
        elif parts == ["route", "next"]:
            self._data["route"]["next"] = []
        elif parts[0] == "status" and len(parts) >= 2:
            node = self._data.get("status", {})
            for p in parts[1:-1]:
                if isinstance(node, dict) and p in node:
                    node = node[p]
                else:
                    raise FileNotFoundError(f"No such file: {ASYA_MSG_ROOT}/{rel_path}")
            key = parts[-1]
            if isinstance(node, dict) and key in node:
                del node[key]
            else:
                raise FileNotFoundError(f"No such file: {ASYA_MSG_ROOT}/{rel_path}")
        else:
            raise PermissionError(f"Cannot remove: {ASYA_MSG_ROOT}/{rel_path}")

    def listdir(self, rel_path):
        """List directory contents."""
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
        parts = clean.split("/")
        if parts[0] == "status":
            node = self._data.get("status", {})
            for p in parts[1:]:
                if isinstance(node, dict) and p in node:
                    node = node[p]
                else:
                    raise NotADirectoryError(f"Not a directory: {ASYA_MSG_ROOT}/{clean}")
            if isinstance(node, dict):
                return list(node.keys())
            raise NotADirectoryError(f"Not a directory: {ASYA_MSG_ROOT}/{clean}")
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
        if parts[0] == "status" and len(parts) >= 2:
            node = self._data.get("status", {})
            for p in parts[1:]:
                if isinstance(node, dict) and p in node:
                    node = node[p]
                else:
                    return False
            return True
        return False

    def isdir(self, rel_path):
        """Check if a virtual path is a directory."""
        clean = rel_path.strip("/")
        if clean in ("", "route", "headers", "status"):
            return True
        parts = clean.split("/")
        if parts[0] == "status" and len(parts) >= 2:
            node = self._data.get("status", {})
            for p in parts[1:]:
                if isinstance(node, dict) and p in node:
                    node = node[p]
                else:
                    return False
            return isinstance(node, dict)
        return False


class _MsgVirtualFile:
    """File-like object backed by _MessageVFS.

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


# --- Builtins Patching ---

_msg_vfs = _MessageVFS()
_original_open = None
_original_listdir = None
_original_path_exists = None
_original_path_isdir = None
_original_remove = None
_original_makedirs = None
_original_rmdir = None


def _patched_open(path, mode="r", *args, **kwargs):
    """Intercept open() for /proc/asya/msg/ paths."""
    path_str = os.fspath(path) if not isinstance(path, str) else path
    if _msg_vfs.active and path_str.startswith(ASYA_MSG_ROOT):
        rel = path_str[len(ASYA_MSG_ROOT) :]
        if not rel:
            raise IsADirectoryError(f"Is a directory: '{path_str}'")
        return _MsgVirtualFile(_msg_vfs, rel, mode)
    return _original_open(path, mode, *args, **kwargs)


def _patched_listdir(path="."):
    path_str = os.fspath(path) if not isinstance(path, str) else path
    if _msg_vfs.active and path_str.startswith(ASYA_MSG_ROOT):
        rel = path_str[len(ASYA_MSG_ROOT) :]
        return _msg_vfs.listdir(rel)
    return _original_listdir(path)


def _patched_path_exists(path):
    path_str = os.fspath(path) if not isinstance(path, str) else path
    if _msg_vfs.active and path_str.startswith(ASYA_MSG_ROOT):
        rel = path_str[len(ASYA_MSG_ROOT) :]
        return _msg_vfs.exists(rel)
    return _original_path_exists(path)


def _patched_path_isdir(path):
    path_str = os.fspath(path) if not isinstance(path, str) else path
    if _msg_vfs.active and path_str.startswith(ASYA_MSG_ROOT):
        rel = path_str[len(ASYA_MSG_ROOT) :]
        return _msg_vfs.isdir(rel)
    return _original_path_isdir(path)


def _patched_remove(path):
    path_str = os.fspath(path) if not isinstance(path, str) else path
    if _msg_vfs.active and path_str.startswith(ASYA_MSG_ROOT):
        rel = path_str[len(ASYA_MSG_ROOT) :]
        return _msg_vfs.remove(rel)
    return _original_remove(path)


def _patched_makedirs(name, mode=0o777, exist_ok=False):
    path_str = os.fspath(name) if not isinstance(name, str) else name
    if _msg_vfs.active and path_str.startswith(ASYA_MSG_ROOT):
        return  # VFS handles nested structure implicitly
    return _original_makedirs(name, mode=mode, exist_ok=exist_ok)


def _patched_rmdir(path):
    path_str = os.fspath(path) if not isinstance(path, str) else path
    if _msg_vfs.active and path_str.startswith(ASYA_MSG_ROOT):
        return  # VFS directory removal handled via remove()
    return _original_rmdir(path)


def _install_msg_hooks():
    """Patch builtins.open and os.* to intercept /proc/asya/msg/ paths.

    Called once at runtime startup. Safe to call multiple times (idempotent).
    """
    global _original_open, _original_listdir
    global _original_path_exists, _original_path_isdir, _original_remove
    global _original_makedirs, _original_rmdir

    if _original_open is not None:
        return

    _original_open = builtins.open
    _original_listdir = os.listdir
    _original_path_exists = os.path.exists
    _original_path_isdir = os.path.isdir
    _original_remove = os.remove
    _original_makedirs = os.makedirs
    _original_rmdir = os.rmdir

    builtins.open = _patched_open
    io.open = _patched_open
    os.listdir = _patched_listdir
    os.path.exists = _patched_path_exists
    os.path.isdir = _patched_path_isdir
    os.remove = _patched_remove
    os.makedirs = _patched_makedirs
    os.rmdir = _patched_rmdir

    logger.info(f"Message VFS hooks installed (root: {ASYA_MSG_ROOT})")


def _call_handler(user_func, arg):
    """Call user handler, transparently supporting both sync and async functions.

    For async handlers (async def), uses asyncio.run() to execute the coroutine.
    For sync handlers, calls directly with zero overhead (single if check).
    """
    if inspect.iscoroutinefunction(user_func):
        return asyncio.run(user_func(arg))
    return user_func(arg)


def _build_frame(payload_value, input_route, vfs_state):
    """Build a response frame with shifted route from VFS state."""
    prev = [*input_route["prev"], input_route["curr"]]
    handler_next = vfs_state["route_next"]

    if handler_next:
        route = {"prev": prev, "curr": handler_next[0], "next": handler_next[1:]}
    else:
        route = {"prev": prev, "curr": "", "next": []}

    frame = {"payload": payload_value, "route": route}
    if vfs_state["headers"]:
        frame["headers"] = vfs_state["headers"]
    if vfs_state.get("status"):
        frame["status"] = vfs_state["status"]
    return frame


def _collect_payload_frames(message, user_func):
    """Collect response frames using VFS for metadata.

    1. Populate VFS from message
    2. Call handler with payload only
    3. Snapshot VFS state (route.next, headers, status) for each frame
    4. Shift route and build frames
    5. Clear VFS
    """
    input_route = message["route"]

    _msg_vfs.populate(message)

    try:
        if inspect.isasyncgenfunction(user_func):

            async def _collect_async():
                frames = []
                async for payload_value in user_func(message["payload"]):
                    vfs_state = _msg_vfs.snapshot()
                    frames.append(_build_frame(payload_value, input_route, vfs_state))
                return frames

            return asyncio.run(_collect_async())

        if inspect.isgeneratorfunction(user_func):
            frames = []
            for payload_value in user_func(message["payload"]):
                vfs_state = _msg_vfs.snapshot()
                frame = _build_frame(payload_value, input_route, vfs_state)
                frames.append(frame)
            return frames

        result = _call_handler(user_func, message["payload"])
        if result is None:
            return []

        vfs_state = _msg_vfs.snapshot()
        return [_build_frame(result, input_route, vfs_state)]
    finally:
        _msg_vfs.clear()


def _handle_invoke(data: bytes, user_func) -> tuple:
    """Process a single invoke request and return (status_code, body_bytes).

    Exposed as a standalone function for unit testing without HTTP machinery.

    Returns:
        (200, b'{"frames": [...]}')  - success
        (204, b'')                   - handler returned None (abort pipeline)
        (400, b'{"error": "..."}')   - message parsing/validation error
        (500, b'{"error": "..."}')   - handler raised an exception
    """
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


# ---------------------------------------------------------------------------
# State Proxy Interception Layer
# Patches Python builtins (open, os.*) so handlers transparently access
# external state backends via HTTP-over-Unix-socket connectors.
# Activated only when ASYA_STATE_PROXY_MOUNTS env var is set.
# ---------------------------------------------------------------------------


def _parse_state_proxy_mounts(mounts_str):
    # type: (str) -> list
    """Parse ASYA_STATE_PROXY_MOUNTS env var.

    Format: {name}:{path}:{options}[;{name}:{path}:{options}]*
    Example: meta:/state/meta:write=buffered;media:/state/media:write=passthrough
    """
    mounts = []
    for entry in mounts_str.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid mount format: {entry!r} (expected name:path:options)")
        name = parts[0]
        path = parts[1]
        options_str = parts[2]
        opts = {}
        for opt in options_str.split(","):
            opt = opt.strip()
            if "=" in opt:
                k, v = opt.split("=", 1)
                opts[k.strip()] = v.strip()
        if not path.endswith("/"):
            path = path + "/"
        socket_path = f"/var/run/asya/state/{name}.sock"
        mounts.append(
            {
                "name": name,
                "path": path,
                "socket": socket_path,
                "write_mode": opts.get("write", "buffered"),
            }
        )
    return mounts


class _UnixHTTPClient(_http_client.HTTPConnection):
    """HTTP connection over Unix socket to state proxy connector."""

    def __init__(self, sock_path):
        _http_client.HTTPConnection.__init__(self, "localhost")
        self._sock_path = sock_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._sock_path)


_STATUS_TO_EXCEPTION = {
    404: FileNotFoundError,
    409: FileExistsError,
    400: ValueError,
    403: PermissionError,
    500: OSError,
    503: ConnectionError,
    504: TimeoutError,
}


def _raise_for_status(resp, key):
    # type: (...) -> None
    """Map HTTP error status to Python exception."""
    if resp.status >= 400:
        try:
            body = json.loads(resp.read())
            msg = body.get("message", "State proxy error")
        except Exception:
            msg = f"State proxy error (status {resp.status})"
        if resp.status == 413:
            raise OSError(errno.EFBIG, msg)
        exc_class = _STATUS_TO_EXCEPTION.get(resp.status, OSError)
        raise exc_class(msg)


def _resolve_mount(path, mounts):
    # type: (str, list) -> tuple
    """Match path against configured mounts. Returns (mount, key) or (None, None)."""
    path_str = os.fspath(path) if hasattr(os, "fspath") else str(path)
    if isinstance(path_str, bytes):
        path_str = path_str.decode("utf-8")
    if not os.path.isabs(path_str):
        return None, None
    normalized = os.path.normpath(path_str)
    for mount in mounts:
        mount_prefix = mount["path"].rstrip("/")
        if normalized == mount_prefix or normalized.startswith(mount_prefix + "/"):
            key = normalized[len(mount_prefix) :]
            if key.startswith("/"):
                key = key[1:]
            return mount, key
    return None, None


class _StateFile:
    """Read wrapper for state proxy responses."""

    def __init__(self, stream, seekable, text_mode=False, encoding="utf-8"):
        self._stream = stream
        self._seekable = seekable
        self._text_mode = text_mode
        self._encoding = encoding
        self._closed = False

    def read(self, size=-1):
        data = self._stream.read(size) if size != -1 else self._stream.read()
        if self._text_mode and isinstance(data, bytes):
            return data.decode(self._encoding)
        return data

    def readline(self, limit=-1):
        if hasattr(self._stream, "readline"):
            line = self._stream.readline(limit) if limit != -1 else self._stream.readline()
        else:
            line = self._stream.readline()
        if self._text_mode and isinstance(line, bytes):
            return line.decode(self._encoding)
        return line

    def readlines(self, _hint=-1):
        return list(self)

    def seek(self, offset, whence=0):
        if not self._seekable:
            raise OSError("seek not supported on passthrough state file")
        return self._stream.seek(offset, whence)

    def tell(self):
        if not self._seekable:
            raise OSError("tell not supported on passthrough state file")
        return self._stream.tell()

    @property
    def closed(self):
        return self._closed

    def close(self):
        if not self._closed:
            self._closed = True
            if hasattr(self._stream, "close"):
                self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __iter__(self):
        while True:
            line = self.readline()
            if not line:
                break
            yield line

    def readable(self):
        return True

    def writable(self):
        return False


class _BufferedWriteFile:
    """Buffers writes in SpooledTemporaryFile, sends PUT on close."""

    def __init__(self, sock_path, key, text_mode=False, encoding="utf-8"):
        self._sock_path = sock_path
        self._key = key
        self._text_mode = text_mode
        self._encoding = encoding
        self._buf = _tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024)  # noqa: SIM115
        self._closed = False

    def write(self, data):
        if self._text_mode and isinstance(data, str):
            data = data.encode(self._encoding)
        return self._buf.write(data)

    def seek(self, offset, whence=0):
        return self._buf.seek(offset, whence)

    def tell(self):
        return self._buf.tell()

    @property
    def closed(self):
        return self._closed

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._buf.seek(0, 2)
        size = self._buf.tell()
        self._buf.seek(0)
        conn = _UnixHTTPClient(self._sock_path)
        conn.request(
            "PUT",
            f"/keys/{self._key}",
            body=self._buf,
            headers={"Content-Length": str(size)},
        )
        resp = conn.getresponse()
        _raise_for_status(resp, self._key)
        self._buf.close()
        conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def readable(self):
        return False

    def writable(self):
        return True


class _PassthroughWriteFile:
    """Streams writes directly to proxy via chunked transfer encoding."""

    def __init__(self, sock_path, key, text_mode=False, encoding="utf-8"):
        self._key = key
        self._text_mode = text_mode
        self._encoding = encoding
        self._conn = _UnixHTTPClient(sock_path)
        self._conn.putrequest("PUT", f"/keys/{key}")
        self._conn.putheader("Transfer-Encoding", "chunked")
        self._conn.endheaders()
        self._closed = False

    def write(self, data):
        if self._text_mode and isinstance(data, str):
            data = data.encode(self._encoding)
        chunk = f"{len(data):x}\r\n".encode() + data + b"\r\n"
        self._conn.send(chunk)
        return len(data)

    @property
    def closed(self):
        return self._closed

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._conn.send(b"0\r\n\r\n")
        resp = self._conn.getresponse()
        _raise_for_status(resp, self._key)
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def readable(self):
        return False

    def writable(self):
        return True

    def seek(self, *_):
        raise OSError("seek not supported on passthrough write")

    def tell(self):
        raise OSError("tell not supported on passthrough write")


def _open_read(sock_path, key, text_mode):
    """Open a state key for reading via HTTP GET."""
    conn = _UnixHTTPClient(sock_path)
    conn.request("GET", f"/keys/{key}")
    resp = conn.getresponse()
    _raise_for_status(resp, key)

    content_length = resp.getheader("Content-Length")
    if content_length:
        buf = _tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024)  # noqa: SIM115
        shutil.copyfileobj(resp, buf)
        buf.seek(0)
        conn.close()
        return _StateFile(buf, seekable=True, text_mode=text_mode)
    else:
        return _StateFile(resp, seekable=False, text_mode=text_mode)


def _open_write(sock_path, key, write_mode, text_mode):
    """Open a state key for writing."""
    if write_mode == "buffered":
        return _BufferedWriteFile(sock_path, key, text_mode=text_mode)
    else:
        return _PassthroughWriteFile(sock_path, key, text_mode=text_mode)


def _install_state_proxy_hooks(mounts_str):
    """Patch Python builtins to intercept file I/O for state mount paths."""
    import builtins

    mounts = _parse_state_proxy_mounts(mounts_str)
    if not mounts:
        return

    logger.info("State proxy mounts: %s", [(m["name"], m["path"]) for m in mounts])

    _original_open = builtins.open
    _original_stat = os.stat
    _original_listdir = os.listdir
    _original_unlink = os.unlink
    _original_makedirs = os.makedirs

    def _patched_open(file, mode="r", *args, **kwargs):
        mount, key = _resolve_mount(file, mounts)
        if mount is None:
            return _original_open(file, mode, *args, **kwargs)
        path_str = os.fspath(file) if hasattr(os, "fspath") else str(file)
        if not key or path_str.endswith("/"):
            raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), file)
        text_mode = "b" not in mode
        if "r" in mode:
            return _open_read(mount["socket"], key, text_mode)
        if any(c in mode for c in "wax"):
            return _open_write(mount["socket"], key, mount["write_mode"], text_mode)
        return _open_read(mount["socket"], key, text_mode)

    def _patched_stat(path, *args, **kwargs):
        mount, key = _resolve_mount(path, mounts)
        if mount is None:
            return _original_stat(path, *args, **kwargs)
        conn = _UnixHTTPClient(mount["socket"])
        conn.request("HEAD", f"/keys/{key}")
        resp = conn.getresponse()
        if resp.status == 404:
            raise FileNotFoundError(2, "No such file or directory", str(path))
        _raise_for_status(resp, key)
        size = int(resp.getheader("Content-Length", "0"))
        is_file = resp.getheader("X-Is-File", "true").lower() == "true"
        mode = _stat_module.S_IFREG | 0o644 if is_file else _stat_module.S_IFDIR | 0o755
        conn.close()
        return os.stat_result((mode, 0, 0, 1, os.getuid(), os.getgid(), size, 0, 0, 0))

    def _patched_listdir(path="."):
        mount, key = _resolve_mount(path, mounts)
        if mount is None:
            return _original_listdir(path)
        if not key.endswith("/"):
            key = key + "/"
        if key == "/":
            key = ""
        conn = _UnixHTTPClient(mount["socket"])
        conn.request("GET", f"/keys/?prefix={key}&delimiter=/")
        resp = conn.getresponse()
        _raise_for_status(resp, key)
        body = json.loads(resp.read())
        conn.close()
        entries = []
        for k in body.get("keys", []):
            name = k[len(key) :] if k.startswith(key) else k
            if name:
                entries.append(name)
        for p in body.get("prefixes", []):
            name = p[len(key) :] if p.startswith(key) else p
            name = name.rstrip("/")
            if name:
                entries.append(name)
        return entries

    def _patched_unlink(path, *args, **kwargs):
        mount, key = _resolve_mount(path, mounts)
        if mount is None:
            return _original_unlink(path, *args, **kwargs)
        conn = _UnixHTTPClient(mount["socket"])
        conn.request("DELETE", f"/keys/{key}")
        resp = conn.getresponse()
        _raise_for_status(resp, key)
        conn.close()

    def _patched_makedirs(name, mode=0o777, exist_ok=False):
        mount, _ = _resolve_mount(name, mounts)
        if mount is None:
            return _original_makedirs(name, mode=mode, exist_ok=exist_ok)

    builtins.open = _patched_open
    os.stat = _patched_stat
    os.listdir = _patched_listdir
    os.unlink = _patched_unlink
    os.remove = _patched_unlink
    os.makedirs = _patched_makedirs

    logger.info("State proxy hooks installed for %d mount(s)", len(mounts))


class _UnixHTTPServer(http.server.HTTPServer):
    """HTTP server that listens on a Unix domain socket."""

    address_family = socket.AF_UNIX

    def server_bind(self):
        with contextlib.suppress(OSError):
            os.unlink(self.server_address)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name = "asya-runtime"
        self.server_port = 0
        if ASYA_SOCKET_CHMOD:
            mode = int(ASYA_SOCKET_CHMOD, 8)
            os.chmod(self.server_address, mode)
        logger.info(f"HTTP server bound to {self.server_address}")

    def server_close(self):
        super().server_close()
        with contextlib.suppress(OSError):
            os.unlink(self.server_address)


class _InvokeHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for POST /invoke."""

    def address_string(self):
        return "unix-client"

    def log_message(self, format, *args):  # noqa: A002
        logger.debug(format, *args)

    def do_POST(self):  # noqa: N802
        if self.path != "/invoke":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, _error_response("msg_parsing_error", ValueError("Missing request body")))
            return

        body = self.rfile.read(content_length)

        try:
            message = _parse_message_json(body)
            if ASYA_ENABLE_VALIDATION:
                message = _validate_message(message)
            logger.debug(f"Received message: {len(body)} bytes")
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, ValueError) as exc:
            self._send_json(400, _error_response("msg_parsing_error", exc))
            return

        try:
            user_func = self.server.user_func
            logger.info(f"[DIAG] Starting handler execution, message_id={message.get('id', 'unknown')}")
            frames = _collect_payload_frames(message, user_func)
        except Exception as exc:
            logger.exception("Fatal error on processing input message")
            self._send_json(500, _error_response("processing_error", exc))
            return

        if not frames:
            self.send_response(204)
            self.end_headers()
        else:
            self._send_json(200, {"frames": frames})

    def do_GET(self):  # noqa: N802
        if self.path == "/healthz":
            self._send_json(200, {"status": "ready"})
        else:
            self.send_error(404)

    def _send_json(self, code, data):
        """Send a JSON response with the given HTTP status code."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _log_env_vars():
    logger.info(
        f"Asya Actor Runtime starting with handler: '{ASYA_HANDLER}' "
        f"(msg_root: {ASYA_MSG_ROOT}, validation: {ASYA_ENABLE_VALIDATION})"
    )
    if logger.isEnabledFor(logging.DEBUG):
        for name, value in os.environ.items():
            if name.startswith("ASYA_"):
                logger.debug(f"Env: {name}={value}")


def handle_requests():
    """Main entry point, blocks forever."""
    _log_env_vars()
    _install_msg_hooks()

    # Activate state proxy interception before loading handler
    state_proxy_mounts = os.environ.get("ASYA_STATE_PROXY_MOUNTS")
    if state_proxy_mounts:
        _install_state_proxy_hooks(state_proxy_mounts)

    func = _load_function()
    server = _UnixHTTPServer(SOCKET_PATH, _InvokeHandler)
    server.user_func = func

    ready_file = f"{SOCKET_DIR}/runtime-ready"
    try:
        os.makedirs(SOCKET_DIR, exist_ok=True)
        with open(ready_file, "w") as f:
            f.write("ready")
        logger.info(f"Runtime ready signal created: {ready_file}")
    except Exception as e:
        logger.error(f"Failed to create ready file {ready_file}: {e}")

    def _shutdown(signum, _frame):
        logger.warning(f"Received signal {signum}, shutting down...")
        server._BaseServer__shutdown_request = True

    try:
        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)
    except ValueError as e:
        logger.debug(f"Cannot set signal handlers (not in main thread): {e}")

    try:
        server.serve_forever()
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        logger.exception("Traceback:")
    finally:
        server.server_close()
        with contextlib.suppress(OSError):
            os.unlink(ready_file)


if __name__ == "__main__":
    handle_requests()
