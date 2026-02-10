#!/usr/bin/env python3
"""
Runtime component tests - Unix socket protocol.

Tests the runtime socket server with mock sidecar client:
- Socket communication with length-prefix protocol
- Handler invocation and response format
- Error responses
"""

import json
import logging
import socket
import struct

import pytest
from asya_testing.fixtures import configure_logging

configure_logging()

logger = logging.getLogger(__name__)


class SocketClient:
    """
    Mock sidecar client for testing runtime socket protocol.

    This is a component-specific test utility for validating the low-level
    Unix socket protocol between sidecar and runtime. It tests the wire format
    (length-prefixed JSON) rather than handler business logic.

    NOT FOR GENERAL USE - Use asya_testing.handlers for testing handler logic.
    """

    def __init__(self, socket_path: str):
        self.socket_path = socket_path

    def _recv_exact(self, sock, n: int) -> bytes:
        """Receive exactly n bytes from socket."""
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Socket closed before receiving all data")
            data += chunk
        return data

    def send_message(self, message: dict, timeout: int = 5) -> list:
        """Send message to runtime and receive streaming response frames.

        Protocol:
        - Send: 4-byte length prefix (big-endian) + JSON data
        - Receive: multiple length-prefixed frames, terminated by {"type": "end"}
        """
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        try:
            sock.connect(self.socket_path)

            # Send message with length prefix
            data = json.dumps(message).encode()
            length_prefix = struct.pack(">I", len(data))
            sock.sendall(length_prefix + data)

            # Read streaming frames until end sentinel
            frames = []
            while True:
                frame_length_bytes = self._recv_exact(sock, 4)
                frame_length = struct.unpack(">I", frame_length_bytes)[0]
                frame_data = self._recv_exact(sock, frame_length)
                frame = json.loads(frame_data.decode())

                if isinstance(frame, dict) and frame.get("type") == "end":
                    break
                frames.append(frame)

            return frames
        finally:
            sock.close()


@pytest.fixture
def echo_client():
    """Socket client for echo runtime."""
    return SocketClient("/var/run/asya/echo.sock")


@pytest.fixture
def error_client():
    """Socket client for error runtime."""
    return SocketClient("/var/run/asya/error.sock")


@pytest.fixture
def timeout_client():
    """Socket client for timeout runtime."""
    return SocketClient("/var/run/asya/timeout.sock")


def test_echo_handler(echo_client):
    """Test echo handler processes payload correctly."""
    message = {
        "id": "test-001",
        "route": {"actors": ["echo"], "current": 0},
        "payload": {"message": "hello"}
    }

    response = echo_client.send_message(message)

    # Runtime returns streaming frames collected into a list
    assert isinstance(response, list)
    assert len(response) == 1

    result = response[0]
    assert "payload" in result
    assert "route" in result
    # Echo handler transforms: {"message": X} → {"echoed": X}
    assert result["payload"] == {"echoed": "hello"}


def test_error_handler(error_client):
    """Test error handler returns error in response."""
    message = {
        "id": "test-002",
        "route": {"actors": ["error"], "current": 0},
        "payload": {"message": "trigger error"}
    }

    response = error_client.send_message(message)

    # Should return list with error message
    assert isinstance(response, list)
    assert len(response) == 1

    result = response[0]
    # Error responses have "error" field
    assert "error" in result
    assert isinstance(result["error"], str)
    assert len(result["error"]) > 0


def test_timeout_handler_fast(timeout_client):
    """Test timeout handler responds for small sleep."""
    message = {
        "id": "test-003",
        "route": {"actors": ["timeout"], "current": 0},
        "payload": {"sleep_seconds": 0.1}
    }

    response = timeout_client.send_message(message)

    # Should complete successfully
    assert isinstance(response, list)
    assert len(response) == 1

    result = response[0]
    # No error for fast response
    assert "error" not in result or result.get("error") == ""


def test_unicode_payload(echo_client):
    """Test runtime handles Unicode correctly."""
    message = {
        "id": "test-004",
        "route": {"actors": ["echo"], "current": 0},
        "payload": {"message": "Hello 世界 🌍"}
    }

    response = echo_client.send_message(message)

    assert isinstance(response, list)
    assert len(response) == 1
    assert "echoed" in response[0]["payload"]


def test_empty_payload(echo_client):
    """Test runtime handles empty payload."""
    message = {
        "id": "test-005",
        "route": {"actors": ["echo"], "current": 0},
        "payload": {}
    }

    response = echo_client.send_message(message)

    # Should still process and return result
    assert isinstance(response, list)
    assert len(response) == 1
    assert "payload" in response[0]


def test_complex_payload(echo_client):
    """Test runtime handles nested/complex payloads."""
    message = {
        "id": "test-006",
        "route": {"actors": ["echo"], "current": 0},
        "payload": {
            "message": {
                "nested": "data",
                "array": [1, 2, 3],
                "bool": True,
                "null": None
            }
        }
    }

    response = echo_client.send_message(message)

    assert isinstance(response, list)
    assert len(response) == 1
    # Echo handler should process it
    assert "echoed" in response[0]["payload"]
