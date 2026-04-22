import http.client
import json
import os
import socket

import pytest


@pytest.fixture(scope="session")
def proxy():
    """HTTP client over Unix socket to the state-proxy-s3kv server."""
    sock_path = os.environ["STATE_PROXY_SOCKET"]

    class UnixHTTPClient:
        def request(self, method: str, path: str, body=None) -> http.client.HTTPResponse:
            conn = http.client.HTTPConnection("localhost")
            conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.sock.connect(sock_path)
            headers = {}
            if body is not None:
                if isinstance(body, dict):
                    body = json.dumps(body).encode()
                headers["Content-Length"] = str(len(body))
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=body, headers=headers)
            return conn.getresponse()

    return UnixHTTPClient()
