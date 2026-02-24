#!/usr/bin/env python3
"""
Runtime component tests - HTTP protocol over Unix socket.

Tests the runtime HTTP server with mock sidecar client:
- HTTP communication over Unix socket (POST /invoke)
- Handler invocation and response format
- Error responses
"""

import http.client as http_client
import json
import logging
import socket

import pytest
from asya_testing.fixtures import configure_logging

configure_logging()

logger = logging.getLogger(__name__)


class _UnixHTTPConnection(http_client.HTTPConnection):
    """HTTP connection over Unix socket."""

    def __init__(self, socket_path):
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._socket_path)


class HTTPClient:
    """
    Mock sidecar client for testing runtime HTTP protocol.

    This is a component-specific test utility for validating the HTTP
    protocol between sidecar and runtime over Unix socket. It tests
    POST /invoke requests rather than handler business logic.

    NOT FOR GENERAL USE - Use asya_testing.handlers for testing handler logic.
    """

    def __init__(self, socket_path: str):
        self.socket_path = socket_path

    def send_message(self, message: dict, timeout: int = 5) -> list:
        """Send message to runtime via HTTP POST /invoke and return response frames.

        Protocol:
        - Send: POST /invoke with JSON body
        - Response 200: {"frames": [...]} - success
        - Response 204: empty body - abort (handler returned None)
        - Response 400: {"error": ..., "details": ...} - bad request
        - Response 500: {"error": ..., "details": ...} - handler error
        """
        conn = _UnixHTTPConnection(self.socket_path)
        conn.timeout = timeout

        try:
            body = json.dumps(message).encode("utf-8")
            conn.request(
                "POST",
                "/invoke",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            status = resp.status
            raw = resp.read()

            if status == 204:
                return []

            if not raw:
                return []

            data = json.loads(raw)

            if status == 200:
                return data["frames"]

            # 400 or 500: return error as single-element list
            return [data]
        finally:
            conn.close()


@pytest.fixture
def echo_client():
    """HTTP client for echo runtime."""
    return HTTPClient("/var/run/asya/echo.sock")


@pytest.fixture
def error_client():
    """HTTP client for error runtime."""
    return HTTPClient("/var/run/asya/error.sock")


@pytest.fixture
def timeout_client():
    """HTTP client for timeout runtime."""
    return HTTPClient("/var/run/asya/timeout.sock")


def test_echo_handler(echo_client):
    """Test echo handler processes payload correctly."""
    message = {
        "id": "test-001",
        "route": {"prev": [], "curr": "echo", "next": []},
        "payload": {"message": "hello"}
    }

    response = echo_client.send_message(message)

    # Runtime returns streaming frames collected into a list
    assert isinstance(response, list)
    assert len(response) == 1

    result = response[0]
    assert "payload" in result
    assert "route" in result
    # Echo handler transforms: {"message": X} -> {"echoed": X}
    assert result["payload"] == {"echoed": "hello"}


def test_error_handler(error_client):
    """Test error handler returns error in response."""
    message = {
        "id": "test-002",
        "route": {"prev": [], "curr": "error", "next": []},
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
        "route": {"prev": [], "curr": "timeout", "next": []},
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
        "route": {"prev": [], "curr": "echo", "next": []},
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
        "route": {"prev": [], "curr": "echo", "next": []},
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
        "route": {"prev": [], "curr": "echo", "next": []},
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
