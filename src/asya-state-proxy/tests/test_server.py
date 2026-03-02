"""Tests for ConnectorServer over a real Unix socket."""

from __future__ import annotations

import http.client
import io
import json
import socket
import threading
from typing import BinaryIO

import pytest
from asya_state_proxy.interface import KeyMeta, ListResult, StateProxyConnector
from asya_state_proxy.server import ConnectorServer


# ---------------------------------------------------------------------------
# In-memory stub connector
# ---------------------------------------------------------------------------


class StubConnector(StateProxyConnector):
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def read(self, key: str) -> BinaryIO:
        if key not in self._store:
            raise FileNotFoundError(f"Key not found: {key}")
        return io.BytesIO(self._store[key])

    def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
        self._store[key] = data.read()

    def exists(self, key: str) -> bool:
        return key in self._store

    def stat(self, key: str) -> KeyMeta | None:
        if key not in self._store:
            return None
        return KeyMeta(size=len(self._store[key]), is_file=True)

    def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
        keys = []
        prefixes_set: set[str] = set()
        for k in self._store:
            if not k.startswith(key_prefix):
                continue
            remainder = k[len(key_prefix) :]
            if delimiter and delimiter in remainder:
                sub = remainder.split(delimiter, 1)[0] + delimiter
                prefixes_set.add(key_prefix + sub)
            else:
                keys.append(k)
        return ListResult(keys=sorted(keys), prefixes=sorted(prefixes_set))

    def delete(self, key: str) -> None:
        if key not in self._store:
            raise FileNotFoundError(f"Key not found: {key}")
        del self._store[key]

    def listxattr(self, key: str) -> list[str]:
        if key not in self._store:
            raise FileNotFoundError(f"Key not found: {key}")
        return ["url", "content_type"]

    def getxattr(self, key: str, attr: str) -> str:
        if key not in self._store:
            raise FileNotFoundError(f"Key not found: {key}")
        if attr == "url":
            return f"stub://{key}"
        if attr == "content_type":
            return "application/octet-stream"
        raise KeyError(f"Unsupported attribute: {attr}")

    def setxattr(self, key: str, attr: str, value: str) -> None:
        if key not in self._store:
            raise FileNotFoundError(f"Key not found: {key}")
        if attr == "content_type":
            return
        if attr == "url":
            raise PermissionError(f"Attribute {attr} is read-only")
        raise KeyError(f"Unsupported attribute: {attr}")


# ---------------------------------------------------------------------------
# Unix socket HTTP client helper
# ---------------------------------------------------------------------------


class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection that connects to a Unix domain socket."""

    def __init__(self, socket_path: str) -> None:
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self._socket_path)
        self.sock = sock


# ---------------------------------------------------------------------------
# Server fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def server_socket(tmp_path):
    socket_path = str(tmp_path / "test.sock")
    connector = StubConnector()
    srv = ConnectorServer(socket_path, connector)

    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    yield socket_path, connector

    srv.shutdown()
    thread.join(timeout=5)
    srv.server_close()


def _request(
    socket_path: str, method: str, path: str, body: bytes = b"", headers: dict | None = None
) -> tuple[int, dict, bytes]:
    conn = _UnixHTTPConnection(socket_path)
    h = headers or {}
    if body:
        h["Content-Length"] = str(len(body))
    conn.request(method, path, body=body if body else None, headers=h)
    resp = conn.getresponse()
    resp_body = resp.read()
    resp_headers = dict(resp.getheaders())
    conn.close()
    return resp.status, resp_headers, resp_body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health_check(server_socket):
    socket_path, _ = server_socket
    status, _, body = _request(socket_path, "GET", "/healthz")
    assert status == 200
    data = json.loads(body)
    assert data == {"status": "ready"}


def test_put_then_get_returns_same_data(server_socket):
    socket_path, _ = server_socket
    payload = b"hello world"
    status, _, _ = _request(socket_path, "PUT", "/keys/mykey", body=payload)
    assert status == 204

    status, _, body = _request(socket_path, "GET", "/keys/mykey")
    assert status == 200
    assert body == payload


def test_get_missing_key_returns_404(server_socket):
    socket_path, _ = server_socket
    status, _, body = _request(socket_path, "GET", "/keys/missing")
    assert status == 404
    data = json.loads(body)
    assert data["error"] == "key_not_found"
    assert "message" in data


def test_head_existing_key_returns_204_with_headers(server_socket):
    socket_path, _ = server_socket
    payload = b"some data"
    _request(socket_path, "PUT", "/keys/headkey", body=payload)

    status, headers, _ = _request(socket_path, "HEAD", "/keys/headkey")
    assert status == 204
    assert headers.get("Content-Length") == str(len(payload))
    assert headers.get("X-Is-File") == "true"


def test_head_missing_key_returns_404(server_socket):
    socket_path, _ = server_socket
    status, _, _ = _request(socket_path, "HEAD", "/keys/noexist")
    assert status == 404


def test_list_keys_with_prefix(server_socket):
    socket_path, _ = server_socket
    _request(socket_path, "PUT", "/keys/a/b/c", body=b"1")
    _request(socket_path, "PUT", "/keys/a/b/d", body=b"2")
    _request(socket_path, "PUT", "/keys/x/y", body=b"3")

    import urllib.parse

    qs = urllib.parse.urlencode({"prefix": "a/", "delimiter": "/"})
    status, _, body = _request(socket_path, "GET", f"/keys/?{qs}")
    assert status == 200
    data = json.loads(body)
    # a/b/c and a/b/d share prefix a/b/
    assert "a/b/" in data["prefixes"]
    assert data["keys"] == []


def test_delete_existing_key_returns_204(server_socket):
    socket_path, _ = server_socket
    _request(socket_path, "PUT", "/keys/delkey", body=b"data")

    status, _, _ = _request(socket_path, "DELETE", "/keys/delkey")
    assert status == 204

    # Key should be gone
    status, _, _ = _request(socket_path, "GET", "/keys/delkey")
    assert status == 404


def test_delete_missing_key_returns_404(server_socket):
    socket_path, _ = server_socket
    status, _, body = _request(socket_path, "DELETE", "/keys/gone")
    assert status == 404
    data = json.loads(body)
    assert data["error"] == "key_not_found"


def test_list_flat_keys_no_delimiter(server_socket):
    socket_path, _ = server_socket
    _request(socket_path, "PUT", "/keys/flat/one", body=b"a")
    _request(socket_path, "PUT", "/keys/flat/two", body=b"b")

    import urllib.parse

    qs = urllib.parse.urlencode({"prefix": "flat/", "delimiter": ""})
    status, _, body = _request(socket_path, "GET", f"/keys/?{qs}")
    assert status == 200
    data = json.loads(body)
    assert "flat/one" in data["keys"]
    assert "flat/two" in data["keys"]


def test_put_empty_body(server_socket):
    socket_path, _ = server_socket
    status, _, _ = _request(socket_path, "PUT", "/keys/empty", body=b"")
    assert status == 204

    status, _, body = _request(socket_path, "GET", "/keys/empty")
    assert status == 200
    assert body == b""


# ---------------------------------------------------------------------------
# Meta endpoint tests (xattr)
# ---------------------------------------------------------------------------


def test_meta_listxattr_returns_attrs(server_socket):
    socket_path, _ = server_socket
    _request(socket_path, "PUT", "/keys/metakey", body=b"data")

    status, _, body = _request(socket_path, "GET", "/meta/metakey")
    assert status == 200
    data = json.loads(body)
    assert "url" in data["attrs"]
    assert "content_type" in data["attrs"]


def test_meta_getxattr_returns_value(server_socket):
    socket_path, _ = server_socket
    _request(socket_path, "PUT", "/keys/metakey", body=b"data")

    status, _, body = _request(socket_path, "GET", "/meta/metakey?attr=url")
    assert status == 200
    data = json.loads(body)
    assert data["attr"] == "url"
    assert data["value"] == "stub://metakey"


def test_meta_getxattr_unsupported_returns_400(server_socket):
    socket_path, _ = server_socket
    _request(socket_path, "PUT", "/keys/metakey", body=b"data")

    status, _, body = _request(socket_path, "GET", "/meta/metakey?attr=nosuch")
    assert status == 400
    data = json.loads(body)
    assert data["error"] == "unsupported_attribute"


def test_meta_getxattr_missing_key_returns_404(server_socket):
    socket_path, _ = server_socket
    status, _, body = _request(socket_path, "GET", "/meta/missing?attr=url")
    assert status == 404


def test_meta_listxattr_missing_key_returns_404(server_socket):
    socket_path, _ = server_socket
    status, _, body = _request(socket_path, "GET", "/meta/missing")
    assert status == 404


def test_meta_setxattr_returns_204(server_socket):
    socket_path, _ = server_socket
    _request(socket_path, "PUT", "/keys/metakey", body=b"data")

    req_body = json.dumps({"value": "text/plain"}).encode()
    status, _, _ = _request(
        socket_path,
        "PUT",
        "/meta/metakey?attr=content_type",
        body=req_body,
        headers={"Content-Type": "application/json"},
    )
    assert status == 204


def test_meta_setxattr_readonly_returns_403(server_socket):
    socket_path, _ = server_socket
    _request(socket_path, "PUT", "/keys/metakey", body=b"data")

    req_body = json.dumps({"value": "x"}).encode()
    status, _, body = _request(
        socket_path,
        "PUT",
        "/meta/metakey?attr=url",
        body=req_body,
        headers={"Content-Type": "application/json"},
    )
    assert status == 403


def test_meta_setxattr_unsupported_returns_400(server_socket):
    socket_path, _ = server_socket
    _request(socket_path, "PUT", "/keys/metakey", body=b"data")

    req_body = json.dumps({"value": "x"}).encode()
    status, _, body = _request(
        socket_path,
        "PUT",
        "/meta/metakey?attr=nosuch",
        body=req_body,
        headers={"Content-Type": "application/json"},
    )
    assert status == 400


def test_meta_setxattr_missing_attr_param_returns_400(server_socket):
    socket_path, _ = server_socket
    _request(socket_path, "PUT", "/keys/metakey", body=b"data")

    req_body = json.dumps({"value": "x"}).encode()
    status, _, body = _request(
        socket_path,
        "PUT",
        "/meta/metakey",
        body=req_body,
        headers={"Content-Type": "application/json"},
    )
    assert status == 400
