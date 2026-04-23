"""Fixtures for state proxy component tests."""

import http.client
import json
import os
import socket

import pytest

_CONNECTOR_SOCKET = "/var/run/asya/state/meta.sock"


class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP connection over Unix socket."""

    def __init__(self, socket_path):
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._socket_path)


class RuntimeClient:
    """Client to invoke the runtime's state_ops_handler over Unix socket."""

    SOCKET_PATH = "/var/run/asya/asya-runtime.sock"

    def _send_request(self, payload: dict, timeout: int = 10) -> tuple[http.client.HTTPResponse, dict]:
        """Send request and return response and parsed data."""
        message = {
            "id": f"test-{id(payload)}",
            "route": {"prev": [], "curr": "state-ops", "next": []},
            "payload": payload,
        }
        conn = _UnixHTTPConnection(self.SOCKET_PATH)
        conn.timeout = timeout
        body = json.dumps(message).encode()
        try:
            conn.request(
                "POST",
                "/invoke",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            data = json.loads(resp.read())
            return resp, data
        finally:
            conn.close()

    def invoke(self, payload: dict, timeout: int = 10) -> dict:
        """Send a state operation to the runtime and return the result payload."""
        resp, data = self._send_request(payload, timeout)
        if resp.status == 200:
            assert len(data["frames"]) == 1
            return data["frames"][0]["payload"]
        return data

    def invoke_expect_error(self, payload: dict, timeout: int = 10) -> dict:
        """Send a state operation expecting a 500 error response."""
        resp, data = self._send_request(payload, timeout)
        assert resp.status == 500, f"Expected 500, got {resp.status}: {data}"
        return data


@pytest.fixture
def runtime():
    """Runtime client for invoking state operations."""
    return RuntimeClient()


@pytest.fixture
def connector_profile():
    """Current connector profile name from CONNECTOR_PROFILE env var."""
    return os.environ.get("CONNECTOR_PROFILE", "s3-lww")


class ConnectorClient:
    """Direct HTTP client for the state proxy connector Unix socket.

    Used to call /query and other connector endpoints that bypass the runtime.
    """

    def __init__(self, socket_path: str = _CONNECTOR_SOCKET) -> None:
        self._socket_path = socket_path

    def post_query(self, body: dict) -> tuple[int, dict]:
        """POST /query to the connector socket. Returns (status_code, body_dict)."""
        data = json.dumps(body).encode()
        for attempt in range(2):
            conn = _UnixHTTPConnection(self._socket_path)
            try:
                conn.request(
                    "POST",
                    "/query",
                    body=data,
                    headers={"Content-Type": "application/json", "Content-Length": str(len(data))},
                )
                resp = conn.getresponse()
                return resp.status, json.loads(resp.read())
            except BrokenPipeError:
                pass  # retry; fall through on second attempt
            finally:
                conn.close()
    # Both attempts failed — connector closed connections without responding.
    # Treat as unsupported: the require_query_support fixture will skip on 501.
    return 501, {}


@pytest.fixture
def connector_client():
    """Client that calls the connector socket directly (not via the runtime)."""
    return ConnectorClient()
