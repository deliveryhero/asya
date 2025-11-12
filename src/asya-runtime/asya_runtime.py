#!/usr/bin/env python3
"""
Asya Actor Runtime - Unix Socket Server
Supported Python versions: 3.7+

Simplified runtime that calls a user-specified Python function or class method.

Handler Types:
    Function handler: Direct function call
        def process(payload: dict) -> dict:
            return {"result": ...}

    Class handler: Stateful handler with initialization
        class Processor:
            def __init__(self, config: str = "/default/path"):
                self.model = load_model(config)  # Init once

            def process(self, payload: dict) -> dict:
                return self.model(payload)  # Called per request

        Note: All __init__ parameters must have default values for zero-arg instantiation.

Environment Variables:
    ASYA_HANDLER: Full path to function or method (e.g., "foo.bar.process" or "foo.bar.Processor.process")
    ASYA_HANDLER_MODE: Handler argument type ("payload" or "envelope", default: "payload")
    ASYA_SOCKET_CHMOD: Socket permissions in octal (default: "0o666", empty = skip chmod)
    ASYA_CHUNK_SIZE: Socket read chunk size in bytes (default: 65536)
    ASYA_ENABLE_VALIDATION: Enable envelope validation ("true" or "false", default: "true")
    ASYA_LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR, default: INFO)

Socket Configuration:
    The socket path defaults to /var/run/asya/asya-runtime.sock and is managed by the operator.
    ASYA_SOCKET_DIR and ASYA_SOCKET_NAME are for internal testing only - DO NOT set in production.
"""

import contextlib
import importlib
import inspect
import json
import logging
import os
import re
import signal
import socket
import struct
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
ASYA_CHUNK_SIZE = int(os.getenv("ASYA_CHUNK_SIZE", 65536))
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
        logger.critical(f"FATAL: Invalid ASYA_HANDLER format: {ASYA_HANDLER}")
        logger.critical("Expected format: 'module.path.function' or 'module.path.Class.method'")
        sys.exit(1)

    # Split into parts and find module boundary by attempting imports
    parts = ASYA_HANDLER.split(".")
    if len(parts) < 2:
        logger.critical(f"FATAL: Invalid ASYA_HANDLER format: {ASYA_HANDLER}")
        logger.critical("Expected format: 'module.path.function' or 'module.path.Class.method'")
        sys.exit(1)

    # Try to find the module by attempting imports with progressively longer paths
    module = None
    module_parts = []
    attr_parts = []

    for i in range(len(parts) - 1, 0, -1):
        module_path = ".".join(parts[:i])
        try:
            module = importlib.import_module(module_path)
            module_parts = parts[:i]
            attr_parts = parts[i:]
            break
        except ImportError:
            continue

    if module is None:
        logger.critical(f"FATAL: Could not import module from {ASYA_HANDLER}")
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


def _recv_exact(sock, n: int) -> bytes:
    """Read exactly n bytes from socket."""
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(min(remaining, ASYA_CHUNK_SIZE))
        if not chunk:
            raise ConnectionError("Connection closed while reading")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _send_envelope(sock, data: bytes):
    """Send envelope with length-prefix (4-byte big-endian uint32)."""
    length = struct.pack(">I", len(data))
    sock.sendall(length + data)


def _setup_socket(socket_path):
    """Initialize Unix socket server."""
    # Remove socket file if it exists
    try:
        os.unlink(socket_path)
    except OSError:
        if os.path.exists(socket_path):
            raise

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(socket_path)
    sock.listen(5)

    # Apply chmod if configured (skip if ASYA_SOCKET_CHMOD is empty)
    if ASYA_SOCKET_CHMOD:
        mode = int(ASYA_SOCKET_CHMOD, 8)  # Parse octal string like "0o660"
        os.chmod(socket_path, mode)
        logger.info(f"Socket permissions set to {ASYA_SOCKET_CHMOD}")

    logger.info(f"Socket server listening on {socket_path}")
    return sock


def _parse_envelope_json(data: bytes) -> dict[str, Any]:
    """Parse received envelope from bytes to dict."""
    return json.loads(data.decode("utf-8"))


def _validate_envelope(
    e: dict,
    expected_current_actor: str | None = None,
    input_route: dict | None = None,
) -> dict:
    if "payload" not in e:
        raise ValueError("Missing required field 'payload' in envelope")
    if "route" not in e:
        raise ValueError("Missing required field 'route' in envelope")

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

    return result


def _get_current_actor(e: dict) -> str:
    actors = e["route"]["actors"]
    current = e["route"]["current"]
    return actors[current]


def _error_response(code: str, exc: Exception | None = None) -> list[dict[str, Any]]:
    """Returns standardized error response dict."""
    error: dict[str, Any] = {"error": code}
    if exc is not None:
        error["details"] = {
            "message": str(exc),
            "type": type(exc).__name__,
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }
    return [error]


def _handle_request(conn: socket.socket, user_func: Any) -> list[dict[str, Any]]:
    """Handle a single request with length-prefix framing."""
    # Read envelope from socket
    try:
        length_bytes = _recv_exact(conn, 4)
        length = struct.unpack(">I", length_bytes)[0]
        data = _recv_exact(conn, length)
    except ConnectionError as exc:
        return _error_response("connection_error", exc)
    except Exception as exc:
        error_trace = traceback.format_exc()
        logger.error(f"ERROR: Connection handling failed:\n{error_trace}")
        return _error_response("connection_error", exc)

    # Parse envelope
    try:
        e: dict[str, Any] = _parse_envelope_json(data)
        if ASYA_ENABLE_VALIDATION:
            e = _validate_envelope(e)
        logger.debug(f"Received envelope: {len(data)} bytes")
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, ValueError) as exc:
        return _error_response("msg_parsing_error", exc)

    # Call user function and process output
    try:
        logger.info(
            f"[DIAG] Starting handler execution, mode={ASYA_HANDLER_MODE}, envelope_id={e.get('id', 'unknown')}"
        )
        out_list: list[dict[str, Any]]
        if ASYA_HANDLER_MODE == "payload":
            # Simple processor: user function expects and returns payload only
            # Runtime auto-increments route.current for normal actors
            # NOTE: End actors should NOT use payload mode - they run in envelope mode
            logger.info(f"[DIAG] Calling user_func with payload: {e['payload']}")
            payload = user_func(e["payload"])  # user function
            logger.info(f"[DIAG] user_func returned: {payload}")
            payload_list: list[Any]
            if payload is None:
                payload_list = []
            elif isinstance(payload, (list, tuple)):
                payload_list = list(payload)
            else:
                payload_list = [payload]

            # Build output route with incremented current (runtime handles routing in payload mode)
            output_route = e["route"].copy()
            output_route["current"] = e["route"]["current"] + 1

            # Build output envelopes with updated route
            out_list = []
            for p in payload_list:
                out: dict[str, Any] = {"payload": p, "route": output_route}
                if "headers" in e:
                    out["headers"] = e["headers"]
                out_list.append(out)

        elif ASYA_HANDLER_MODE == "envelope":
            # Full envelope mode: user function gets complete envelope structure
            # Handler is responsible for route management (including incrementing current)
            # End actors use this mode and return empty dict {} (no routing)
            out = user_func(e)  # user function
            if out is None:
                out_list = []
            elif isinstance(out, (list, tuple)):
                out_list = list(out)
            else:
                out_list = [out]

            # Output validation (only when enabled)
            if ASYA_ENABLE_VALIDATION:
                for i, out in enumerate(out_list):
                    try:
                        out_list[i] = _validate_envelope(
                            out,
                            expected_current_actor=_get_current_actor(e),
                            input_route=e["route"],
                        )
                    except ValueError as exc:
                        raise ValueError(f"Invalid output envelope[{i}/{len(out_list)}]: {exc}") from exc

        else:
            raise ValueError(f"Invalid ASYA_HANDLER_MODE={ASYA_HANDLER_MODE}: not in {VALID_ASYA_HANDLER_MODES}")

        logger.info(f"[DIAG] Handler completed successfully: returning {len(out_list)} response(s)")
        return out_list

    except Exception as exc:
        logger.error(f"[DIAG] Exception caught in handler: type={type(exc).__name__}, msg={exc}")
        logger.exception("Fatal error on processing input envelope")
        return _error_response("processing_error", exc)


def _log_env_vars():
    logger.info(
        f"Asya Actor Runtime starting with handler: {ASYA_HANDLER} "
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
    sock = _setup_socket(SOCKET_PATH)

    # Signal sidecar that runtime is ready to receive messages
    ready_file = f"{SOCKET_DIR}/runtime-ready"
    try:
        os.makedirs(SOCKET_DIR, exist_ok=True)
        with open(ready_file, "w") as f:
            f.write("ready")
        logger.info(f"Runtime ready signal created: {ready_file}")
    except Exception as e:
        logger.error(f"Failed to create ready file {ready_file}: {e}")

    def _cleanup(signum=None, _frame=None):
        """Clean up socket and ready file, then exit."""
        logger.warning(f"Received signal {signum}, shutting down...")
        sock.close()
        with contextlib.suppress(OSError):
            os.unlink(SOCKET_PATH)
        with contextlib.suppress(OSError):
            os.unlink(ready_file)

    # Signal handlers only work in main thread
    try:
        signal.signal(signal.SIGTERM, _cleanup)
        signal.signal(signal.SIGINT, _cleanup)
    except ValueError as e:
        # Running in non-main thread (e.g., tests)
        logger.debug(f"Cannot set signal handlers (not in main thread): {e}")

    try:
        while True:
            try:
                conn, _ = sock.accept()
            except (ConnectionAbortedError, OSError) as e:
                logger.debug(f"Error: {type(e)}: {e}")
                break

            try:
                responses: list[dict] = _handle_request(conn, func)
                response_data = json.dumps(responses).encode("utf-8")
                _send_envelope(conn, response_data)

            except BrokenPipeError:
                logger.warning("Client disconnected")

            except Exception as e:
                logger.critical(f"Failed to send response: {type(e)}: {e}")

            finally:
                conn.close()

    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        logger.exception("Traceback:")
    finally:
        _cleanup()


if __name__ == "__main__":
    handle_requests()
