#!/usr/bin/env python3
"""
Asya Actor Runtime - Unix Socket Server

Simplified runtime that calls a user-specified Python function.

Environment Variables:
    ASYA_SOCKET_PATH: Path to Unix socket (default: /tmp/sockets/app.sock)
    ASYA_SOCKET_CHMOD: Socket permissions in octal (default: "0o660", empty = skip chmod)
    ASYA_HANDLER: Full function path (e.g., "foo.bar.predict")
    ASYA_LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR, default: INFO)
"""

import importlib
import json
import logging
import os
import re
import signal
import socket
import struct
import sys
import traceback
from typing import Any, Dict, Optional

# Configure logging
log_level = os.getenv("ASYA_LOG_LEVEL", "INFO").upper()
log_level_value = getattr(logging, log_level, logging.INFO)
logging.basicConfig(
    level=log_level_value,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("asya.runtime")

# Configuration
ASYA_HANDLER = os.getenv("ASYA_HANDLER", "")
ASYA_HANDLER_ARG_TYPE = os.getenv("ASYA_HANDLER_ARG_TYPE", "payload").lower()
ASYA_SOCKET_PATH = os.getenv("ASYA_SOCKET_PATH", "/tmp/sockets/app.sock")
ASYA_SOCKET_CHMOD = os.getenv("ASYA_SOCKET_CHMOD", "0o660")  # Empty string = skip chmod
ASYA_CHUNK_SIZE = int(os.getenv("ASYA_CHUNK_SIZE", 65536))  # 64KB
ASYA_ENABLE_VALIDATION = os.getenv("ASYA_ENABLE_VALIDATION", "true").lower() == "true"

VALID_ASYA_HANDLER_ARG_TYPES = ("message", "payload")


def _load_function():
    """Load the user function from ASYA_HANDLER env var."""
    if ASYA_HANDLER_ARG_TYPE not in VALID_ASYA_HANDLER_ARG_TYPES:
        raise ValueError(
            f"Invalid ASYA_HANDLER_ARG_TYPE={ASYA_HANDLER_ARG_TYPE}: not in {VALID_ASYA_HANDLER_ARG_TYPES}"
        )

    if not ASYA_HANDLER:
        logger.error("FATAL: ASYA_HANDLER not set")
        sys.exit(1)

    # Validate ASYA_HANDLER format to prevent path traversal and injection attacks
    # Allows: letters, numbers, underscores, dots (standard Python module paths)
    # Example valid: "my_module.submodule.function_name"
    # Example invalid: "../etc/passwd", "os;rm -rf /", "__import__('os').system('cmd')"
    handler_pattern = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+$")
    if not handler_pattern.match(ASYA_HANDLER):
        logger.error(f"FATAL: Invalid ASYA_HANDLER format: {ASYA_HANDLER}")
        logger.error(
            "Expected format: 'module.path.function_name' "
            "(letters, numbers, underscores, and dots only)"
        )
        sys.exit(1)

    # Parse "foo.bar.baz.func" -> module="foo.bar.baz", func="func"
    parts = ASYA_HANDLER.rsplit(".", 1)
    if len(parts) != 2:
        logger.error(f"FATAL: Invalid ASYA_HANDLER format: {ASYA_HANDLER}")
        logger.error("Expected format: 'module.path.function_name'")
        sys.exit(1)

    module_path, func_name = parts

    try:
        logger.info(f"Loading asya handler: module={module_path} function={func_name}")
        module = importlib.import_module(module_path)
        user_func = getattr(module, func_name)

        if not callable(user_func):
            raise TypeError(f"{ASYA_HANDLER} is not callable")

        # TODO: check function's signature and compare with ASYA_HANDLER_ARG_TYPE to fail fast

        logger.info(f"Loaded function: {ASYA_HANDLER}")
        return user_func

    except Exception as e:
        logger.critical(
            f"Failed to load asya handler {ASYA_HANDLER}: {type(e).__name__}: {e}"
        )
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


def _send_msg(sock, data: bytes):
    """Send message with length-prefix (4-byte big-endian uint32)."""
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


def _parse_msg_json(data: bytes) -> Dict[str, Any]:
    """Parse received message from bytes to dict."""
    return json.loads(data.decode("utf-8"))


def _validate_message_syntax(
    msg: dict, expected_current_step: Optional[str] = None
) -> dict:
    if "payload" not in msg:
        raise ValueError("Missing required field 'payload' in message")
    if "route" not in msg:
        raise ValueError("Missing required field 'route' in message")

    # Validate route structure
    route = msg["route"]
    if not isinstance(route, dict):
        raise ValueError("Field 'route' must be a dict")
    if "steps" not in route:
        raise ValueError("Missing required field 'steps' in route")
    if not isinstance(route["steps"], list):
        raise ValueError("Field 'route.steps' must be a list")
    if "current" not in route:
        raise ValueError("Missing required field 'current' in route")
    if not isinstance(route["current"], int):
        raise ValueError("Field 'route.current' must be an integer")

    # Get current actor name from route (trusted value)
    current_idx = route["current"]
    if current_idx < 0 or current_idx >= len(route["steps"]):
        raise ValueError(
            f"Invalid route.current={current_idx}: out of bounds for steps of length {len(route['steps'])}"
        )
    if expected_current_step is not None:
        actual_current_step = route["steps"][current_idx]
        if actual_current_step != expected_current_step:
            raise ValueError(
                f"Route mismatch: input route points to '{expected_current_step}', "
                f"but output route points to '{actual_current_step}'. "
                f"Actor cannot change its current position in the route."
            )

    return {
        "payload": msg["payload"],
        "route": msg["route"],
    }


def _get_current_step(msg: dict) -> str:
    steps = msg["route"]["steps"]
    current = msg["route"]["current"]
    return steps[current]


def _error_response(code: str, exc=None) -> list[dict]:
    """Returns standardized error response dict."""
    error = {"error": code}
    if exc is not None:
        error["details"] = {
            "message": str(exc),
            "type": type(exc).__name__,
            "traceback": "".join(traceback.format_exception(exc)),
        }
    return [error]


def _handle_request(conn, user_func) -> list[dict]:
    """Handle a single request with length-prefix framing."""
    # Read message from socket
    try:
        length_bytes = _recv_exact(conn, 4)
        length = struct.unpack(">I", length_bytes)[0]
        data = _recv_exact(conn, length)
    except ConnectionError as e:
        return _error_response("connection_error", e)
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"ERROR: Connection handling failed:\n{error_trace}")
        return _error_response("connection_error", e)

    # Parse message
    try:
        msg = _parse_msg_json(data)
        if ASYA_ENABLE_VALIDATION:
            msg = _validate_message_syntax(msg)
        logger.debug(f"Received message: {len(data)} bytes")
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, ValueError) as e:
        return _error_response("msg_parsing_error", e)

    # Call user function and process output
    try:
        if ASYA_HANDLER_ARG_TYPE == "payload":
            # simple processor case: user function expects and returns payload only
            out_payload = user_func(msg["payload"])  # user function
            if out_payload is None:
                out_payloads = []
            elif isinstance(out_payload, (list, tuple)):
                out_payloads = list(out_payload)
            else:
                out_payloads = [out_payload]
            out_msgs = [{"payload": p, "route": msg["route"]} for p in out_payloads]

        elif ASYA_HANDLER_ARG_TYPE == "message":
            # complex router case: user function expects and returns
            # the whole message: `{"payload": ..., "route": ...}`
            out_msg = user_func(msg)  # user function
            if out_msg is None:
                out_msgs = []
            elif isinstance(out_msg, (list, tuple)):
                out_msgs = list(out_msg)
            else:
                out_msgs = [out_msg]

            # Output validation (only when enabled)
            if ASYA_ENABLE_VALIDATION:
                for i, out_msg in enumerate(out_msgs):
                    try:
                        out_msg = _validate_message_syntax(
                            out_msg, expected_current_step=_get_current_step(msg)
                        )
                    except ValueError as e:
                        raise ValueError(
                            f"Invalid output message[{i}/{len(out_msgs)}]: {e}"
                        ) from e

        else:
            raise ValueError(
                f"Invalid ASYA_HANDLER_ARG_TYPE={ASYA_HANDLER_ARG_TYPE}: not in {VALID_ASYA_HANDLER_ARG_TYPES}"
            )

        logger.debug(f"Handler completed: returning {len(out_msgs)} response(s)")
        return out_msgs

    except Exception as e:
        logger.exception("Fatal error on processing input message")
        return _error_response("processing_error", e)


def handle_requests():
    """Main entry point, blocks forever."""
    logger.info("Asya Actor Runtime starting...")
    logger.info(f"Log level: {log_level}")
    logger.info(f"Function: {ASYA_HANDLER}")
    logger.info(f"Function argument type: {ASYA_HANDLER}")
    logger.info(f"Socket: {ASYA_SOCKET_PATH}")
    logger.info(f"Socket chmod: {ASYA_SOCKET_CHMOD} (empty string to disable)")

    func = _load_function()
    sock = _setup_socket(ASYA_SOCKET_PATH)

    def _cleanup(signum=None, frame=None):
        """Clean up socket and exit."""
        logger.warning(f"Received signal {signum}, shutting down...")
        sock.close()
        try:
            os.unlink(ASYA_SOCKET_PATH)
        except OSError:
            pass

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    try:
        while True:
            try:
                logger.debug(f"Connecting to socket: {ASYA_SOCKET_PATH}")
                conn, _ = sock.accept()
            except (ConnectionAbortedError, OSError) as e:
                logger.debug(f"Error: {type(e)}: {e}")
                break

            try:
                responses: list[dict] = _handle_request(conn, func)
                response_data = json.dumps(responses).encode("utf-8")
                _send_msg(conn, response_data)

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
