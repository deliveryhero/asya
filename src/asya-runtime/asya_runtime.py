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
    ASYA_HANDLER_MODE: Handler argument type ("payload" or "envelope", default: "payload")
    ASYA_SOCKET_CHMOD: Socket permissions in octal (default: "0o666", empty = skip chmod)
    ASYA_ENABLE_VALIDATION: Enable message validation ("true" or "false", default: "true")
    ASYA_LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR, default: INFO)

Socket Configuration:
    The socket path defaults to /var/run/asya/asya-runtime.sock and is managed by the operator.
    ASYA_SOCKET_DIR and ASYA_SOCKET_NAME are for internal testing only - DO NOT set in production.
"""

import asyncio
import contextlib
import http.server
import importlib
import inspect
import json
import logging
import os
import re
import signal
import socket
import sys
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
ASYA_HANDLER_MODE = (os.getenv("ASYA_HANDLER_MODE") or "payload").lower()
ASYA_SOCKET_CHMOD = os.getenv("ASYA_SOCKET_CHMOD", "0o666")
ASYA_ENABLE_VALIDATION = os.getenv("ASYA_ENABLE_VALIDATION", "true").lower() == "true"

# Socket configuration - hard-coded, managed by operator
# ASYA_SOCKET_DIR and ASYA_SOCKET_NAME are for internal testing only - DO NOT set in production
SOCKET_DIR = os.getenv("ASYA_SOCKET_DIR", "/var/run/asya")
SOCKET_NAME = os.getenv("ASYA_SOCKET_NAME", "asya-runtime.sock")
SOCKET_PATH = os.path.join(SOCKET_DIR, SOCKET_NAME)

VALID_ASYA_HANDLER_MODES = ("payload", "envelope")


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
    if ASYA_HANDLER_MODE not in VALID_ASYA_HANDLER_MODES:
        raise ValueError(f"Invalid ASYA_HANDLER_MODE={ASYA_HANDLER_MODE}: not in {VALID_ASYA_HANDLER_MODES}")

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
    e: dict,
    expected_current_actor: str | None = None,
    input_route: dict | None = None,
) -> dict:
    if "payload" not in e:
        raise ValueError("Missing required field 'payload' in message")
    if "route" not in e:
        raise ValueError("Missing required field 'route' in message")

    # Validate route structure
    route = e["route"]
    if not isinstance(route, dict):
        raise ValueError("Field 'route' must be a dict")
    if "actors" not in route:
        raise ValueError("Missing required field 'actors' in route")
    if not isinstance(route["actors"], list):
        raise ValueError("Field 'route.actors' must be a list")

    # Default current to 0 if not present (sidecar may omit it)
    if "current" not in route:
        logger.info("Field 'route.current' missing, defaulting to 0")
        route["current"] = 0
    if not isinstance(route["current"], int):
        raise ValueError("Field 'route.current' must be an integer")

    # Validate that actors array is non-empty
    if len(route["actors"]) == 0:
        raise ValueError("Field 'route.actors' cannot be empty")

    # Get current actor name from route (trusted value)
    # Allow current to equal len(actors) to signal end-of-route
    current_idx = route["current"]
    if current_idx < 0 or current_idx > len(route["actors"]):
        raise ValueError(
            f"Invalid route.current={current_idx}: out of bounds for actors of length {len(route['actors'])}"
        )

    # Validate headers if present
    if "headers" in e and not isinstance(e["headers"], dict):
        raise ValueError("Field 'headers' must be a dict")

    # Validate that already-processed actors haven't been erased.
    # This check must come BEFORE expected_current_actor validation
    # Runtime can add new actors but cannot remove actors that were already processed
    if input_route is not None:
        input_actors = input_route.get("actors", [])
        input_current = input_route.get("current", 0)
        output_actors = route["actors"]

        # Check that all actors up to and including current are preserved
        processed_actors = input_actors[: input_current + 1]
        output_prefix = output_actors[: len(processed_actors)]

        if output_prefix != processed_actors:
            raise ValueError(
                f"Route modification error: already-processed actors cannot be erased. "
                f"Input route had {processed_actors} (actors 0-{input_current}), "
                f"but output route starts with {output_prefix}. "
                f"Runtimes can add future actors but must preserve all actors up to current."
            )

    # Only validate current actor if we have input_route context
    # Validate that the actor at the INPUT position hasn't been changed
    if expected_current_actor is not None and input_route is not None:
        input_current = input_route.get("current", 0)
        # Check that the actor at the INPUT's current position hasn't changed
        if input_current < len(route["actors"]):
            actual_current_actor = route["actors"][input_current]
            if actual_current_actor != expected_current_actor:
                raise ValueError(
                    f"Route mismatch: input route points to '{expected_current_actor}' at position {input_current}, "
                    f"but output route has '{actual_current_actor}' at that position. "
                    f"Actor cannot change its position in the route."
                )

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
    actors = message["route"]["actors"]
    current = message["route"]["current"]
    return actors[current]


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


def _call_handler(user_func, arg):
    """Call user handler, transparently supporting both sync and async functions.

    For async handlers (async def), uses asyncio.run() to execute the coroutine.
    For sync handlers, calls directly with zero overhead (single if check).
    """
    if inspect.iscoroutinefunction(user_func):
        return asyncio.run(user_func(arg))
    return user_func(arg)


def _collect_payload_frames(message, user_func):
    """Collect response frames for payload mode handlers."""
    output_route = message["route"].copy()
    output_route["current"] = message["route"]["current"] + 1
    headers = message.get("headers")
    status = message.get("status")

    def _build_frame(payload_value):
        frame = {"payload": payload_value, "route": output_route}
        if headers is not None:
            frame["headers"] = headers
        if status is not None:
            frame["status"] = status
        return frame

    if inspect.isgeneratorfunction(user_func):
        return [_build_frame(p) for p in user_func(message["payload"])]

    result = _call_handler(user_func, message["payload"])
    if result is None:
        return []
    return [_build_frame(result)]


def _collect_envelope_frames(message, user_func):
    """Collect response frames for envelope mode handlers."""
    if inspect.isgeneratorfunction(user_func):
        frames = []
        for out in user_func(message):
            if ASYA_ENABLE_VALIDATION:
                out = _validate_message(
                    out,
                    expected_current_actor=_get_current_actor(message),
                    input_route=message["route"],
                )
            frames.append(out)
        return frames

    result = _call_handler(user_func, message)
    if result is None:
        return []
    if ASYA_ENABLE_VALIDATION:
        result = _validate_message(
            result,
            expected_current_actor=_get_current_actor(message),
            input_route=message["route"],
        )
    return [result]


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
            logger.info(
                f"[DIAG] Starting handler execution, mode={ASYA_HANDLER_MODE}, "
                f"message_id={message.get('id', 'unknown')}"
            )
            if ASYA_HANDLER_MODE == "payload":
                frames = _collect_payload_frames(message, user_func)
            elif ASYA_HANDLER_MODE == "envelope":
                frames = _collect_envelope_frames(message, user_func)
            else:
                raise ValueError(f"Invalid ASYA_HANDLER_MODE={ASYA_HANDLER_MODE}: not in {VALID_ASYA_HANDLER_MODES}")
        except Exception as exc:
            logger.exception("Fatal error on processing input message")
            self._send_json(500, _error_response("processing_error", exc))
            return

        if not frames:
            self.send_response(204)
            self.end_headers()
        else:
            self._send_json(200, {"frames": frames})

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
        f"(mode: {ASYA_HANDLER_MODE}, validation: {ASYA_ENABLE_VALIDATION})"
    )
    if logger.isEnabledFor(logging.DEBUG):
        for name, value in os.environ.items():
            if name.startswith("ASYA_"):
                logger.debug(f"Env: {name}={value}")


def handle_requests():
    """Main entry point, blocks forever."""
    _log_env_vars()

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
