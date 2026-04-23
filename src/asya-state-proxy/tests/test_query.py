"""Tests for ObjectStoreQueryMixin and DuckDB-based /query.

Unit tests cover:
  - Helper functions (_validate_field, _build_where, _build_order) — no external deps
  - ObjectStoreQueryMixin.query() SQL logic via a stub connector + real DuckDB
  - S3BufferedLWW.query() using moto for S3 + the temp-file fallback path
    (moto does not intercept DuckDB httpfs, so httpfs is tested separately below)
  - HTTP server /query endpoint

S3 httpfs integration (real LocalStack/MinIO) is covered in component tests.
"""

from __future__ import annotations

import io
import json
import socket
import tempfile
import threading

import boto3
import pytest
from asya_state_proxy.connectors._query import (
    ObjectStoreQueryMixin,
    QueryRequest,
    _build_order,
    _build_where,
    _validate_field,
)
from asya_state_proxy.connectors.s3_buffered_lww.connector import S3BufferedLWW
from asya_state_proxy.interface import KeyMeta, ListResult, StateProxyConnector
from asya_state_proxy.server import ConnectorServer
from moto import mock_aws


TEST_BUCKET = "query-test-bucket"
TEST_REGION = "us-east-1"


# ---------------------------------------------------------------------------
# Stub connector — in-memory dict, no S3; uses temp-file query path
# ---------------------------------------------------------------------------


class _StubConnector(ObjectStoreQueryMixin, StateProxyConnector):
    """In-memory connector for testing the query SQL logic without S3."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def _put(self, key: str, doc: dict) -> None:
        self._store[key] = json.dumps(doc).encode()

    def read(self, key: str) -> io.BytesIO:
        if key not in self._store:
            raise FileNotFoundError(key)
        return io.BytesIO(self._store[key])

    def write(self, key: str, data: io.IOBase, size: int | None = None, *, exclusive: bool = False) -> None:
        self._store[key] = data.read()  # type: ignore[arg-type]

    def exists(self, key: str) -> bool:
        return key in self._store

    def stat(self, key: str) -> KeyMeta | None:
        if key not in self._store:
            return None
        return KeyMeta(size=len(self._store[key]), is_file=True)

    def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
        matching = [k for k in self._store if k.startswith(key_prefix)]
        if not delimiter:
            return ListResult(keys=matching, prefixes=[])
        keys = []
        prefixes: set[str] = set()
        for k in matching:
            rest = k[len(key_prefix) :]
            if delimiter in rest:
                prefixes.add(key_prefix + rest.split(delimiter)[0] + delimiter)
            else:
                keys.append(k)
        return ListResult(keys=keys, prefixes=sorted(prefixes))

    def delete(self, key: str) -> None:
        if key not in self._store:
            raise FileNotFoundError(key)
        del self._store[key]


# ---------------------------------------------------------------------------
# S3 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("STATE_BUCKET", TEST_BUCKET)
    monkeypatch.setenv("AWS_REGION", TEST_REGION)
    monkeypatch.delenv("STATE_PREFIX", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")


@pytest.fixture()
def s3_bucket():
    with mock_aws():
        client = boto3.client("s3", region_name=TEST_REGION)
        client.create_bucket(Bucket=TEST_BUCKET)
        yield client


@pytest.fixture()
def s3_connector(s3_bucket):
    """S3BufferedLWW patched to use the temp-file query path (bypasses httpfs)."""
    c = S3BufferedLWW()
    # Redirect query to the generic temp-file implementation so moto intercepts reads.
    c._setup_duckdb_source = ObjectStoreQueryMixin._setup_duckdb_source.__get__(c)
    return c


def _put_s3(connector: S3BufferedLWW, key: str, doc: dict) -> None:
    data = json.dumps(doc).encode()
    connector.write(key, io.BytesIO(data), size=len(data))


# ---------------------------------------------------------------------------
# Unit tests: helper functions (no external deps)
# ---------------------------------------------------------------------------


def test_validate_field_accepts_valid() -> None:
    _validate_field("status")
    _validate_field("model_name")
    _validate_field("a.b.c")


def test_validate_field_rejects_injection() -> None:
    with pytest.raises(ValueError, match="invalid field name"):
        _validate_field("status; DROP TABLE")


def test_validate_field_rejects_empty() -> None:
    with pytest.raises(ValueError, match="invalid field name"):
        _validate_field("")


def test_build_where_empty() -> None:
    clause, params = _build_where({})
    assert clause == ""
    assert params == []


def test_build_where_single() -> None:
    clause, params = _build_where({"status": "done"})
    assert "json_extract_string" in clause
    assert "$.status" in clause
    assert params == ["done"]


def test_build_where_multiple() -> None:
    clause, params = _build_where({"status": "done", "model": "sdxl"})
    assert clause.count("json_extract_string") == 2
    assert "AND" in clause


def test_build_order_empty() -> None:
    assert _build_order([]) == ""


def test_build_order_asc_desc() -> None:
    result = _build_order(["status", "-created_at"])
    assert "ASC" in result
    assert "DESC" in result


# ---------------------------------------------------------------------------
# Integration tests: query via _StubConnector + real DuckDB (no S3)
# ---------------------------------------------------------------------------


def test_stub_query_empty_returns_zero() -> None:
    c = _StubConnector()
    result = c.query(QueryRequest())
    assert result.total == 0
    assert result.rows == []


def test_stub_query_returns_all_docs() -> None:
    c = _StubConnector()
    c._put("task/a", {"id": "a", "status": "done"})
    c._put("task/b", {"id": "b", "status": "running"})

    result = c.query(QueryRequest())
    assert result.total == 2
    assert len(result.rows) == 2


def test_stub_query_filter_by_field() -> None:
    c = _StubConnector()
    c._put("task/a", {"id": "a", "status": "done"})
    c._put("task/b", {"id": "b", "status": "running"})
    c._put("task/c", {"id": "c", "status": "done"})

    result = c.query(QueryRequest(filter={"status": "done"}))
    assert result.total == 2
    assert {r["id"] for r in result.rows} == {"a", "c"}


def test_stub_query_filter_no_match() -> None:
    c = _StubConnector()
    c._put("task/a", {"id": "a", "status": "done"})

    result = c.query(QueryRequest(filter={"status": "pending"}))
    assert result.total == 0
    assert result.rows == []


def test_stub_query_prefix_scopes_results() -> None:
    c = _StubConnector()
    c._put("run-1/result", {"run": "1"})
    c._put("run-2/result", {"run": "2"})
    c._put("archive/old", {"run": "0"})

    result = c.query(QueryRequest(prefix="run-1"))
    assert result.total == 1
    assert result.rows[0]["run"] == "1"


def test_stub_query_limit_and_offset() -> None:
    c = _StubConnector()
    for i in range(5):
        c._put(f"item/{i}", {"idx": str(i)})

    page1 = c.query(QueryRequest(limit=2, offset=0))
    page2 = c.query(QueryRequest(limit=2, offset=2))

    assert len(page1.rows) == 2
    assert len(page2.rows) == 2
    assert {r["idx"] for r in page1.rows}.isdisjoint({r["idx"] for r in page2.rows})


def test_stub_query_sort_ascending() -> None:
    c = _StubConnector()
    for name in ("c", "a", "b"):
        c._put(f"t/{name}", {"name": name})

    result = c.query(QueryRequest(sort=["name"]))
    names = [r["name"] for r in result.rows]
    assert names == sorted(names)


def test_stub_query_sort_descending() -> None:
    c = _StubConnector()
    for name in ("c", "a", "b"):
        c._put(f"t/{name}", {"name": name})

    result = c.query(QueryRequest(sort=["-name"]))
    names = [r["name"] for r in result.rows]
    assert names == sorted(names, reverse=True)


def test_stub_query_total_reflects_unfiltered_count() -> None:
    c = _StubConnector()
    for i in range(4):
        c._put(f"item/{i}", {"v": str(i % 2)})

    result = c.query(QueryRequest(filter={"v": "0"}, limit=1))
    assert result.total == 2  # total matching, not capped by limit
    assert len(result.rows) == 1


def test_stub_query_invalid_filter_field_raises() -> None:
    c = _StubConnector()
    c._put("item/1", {"status": "ok"})
    with pytest.raises(ValueError, match="invalid field name"):
        c.query(QueryRequest(filter={"bad field!": "x"}))


def test_stub_query_non_json_doc_skipped() -> None:
    c = _StubConnector()
    c._store["corrupt"] = b"not json {{"
    c._put("good/doc", {"status": "ok"})

    result = c.query(QueryRequest())
    assert result.total >= 1


# ---------------------------------------------------------------------------
# S3BufferedLWW query tests via moto (temp-file path)
# ---------------------------------------------------------------------------


def test_s3_query_empty_returns_zero(s3_connector) -> None:
    result = s3_connector.query(QueryRequest())
    assert result.total == 0
    assert result.rows == []


def test_s3_query_filter_and_prefix(s3_connector) -> None:
    _put_s3(s3_connector, "run-1/result", {"model": "sdxl", "status": "done"})
    _put_s3(s3_connector, "run-2/result", {"model": "sdxl", "status": "running"})
    _put_s3(s3_connector, "archive/old", {"model": "other", "status": "done"})

    result = s3_connector.query(QueryRequest(prefix="run-", filter={"status": "done"}))
    assert result.total == 1
    assert result.rows[0]["model"] == "sdxl"


# ---------------------------------------------------------------------------
# HTTP server /query endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def stub_server():
    c = _StubConnector()
    c._put("doc/a", {"status": "done", "n": "1"})
    c._put("doc/b", {"status": "running", "n": "2"})

    with tempfile.NamedTemporaryFile(suffix=".sock", delete=True) as f:
        sock_path = f.name

    srv = ConnectorServer(sock_path, c)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield sock_path, c
    srv.shutdown()


def _post_query(sock_path: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(sock_path)
    request = (
        f"POST /query HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(data)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode() + data
    sock.sendall(request)

    response = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk
    sock.close()

    header, _, body_bytes = response.partition(b"\r\n\r\n")
    status_line = header.split(b"\r\n")[0]
    status_code = int(status_line.split(b" ")[1])
    return status_code, json.loads(body_bytes)


def test_server_query_returns_rows(stub_server) -> None:
    sock_path, _ = stub_server
    code, body = _post_query(sock_path, {"filter": {"status": "done"}})
    assert code == 200
    assert body["total"] == 1
    assert body["rows"][0]["n"] == "1"


def test_server_query_missing_duckdb_returns_501(stub_server) -> None:
    """If connector doesn't implement ObjectStoreQueryMixin, server returns 501."""
    sock_path, _ = stub_server

    class _NoQuery(StateProxyConnector):
        def read(self, k): ...  # type: ignore[override]
        def write(self, k, d, s=None, *, exclusive=False): ...
        def exists(self, k):
            return False

        def stat(self, k):
            return None

        def list(self, p, d="/"):
            return ListResult([], [])

        def delete(self, k): ...

    with tempfile.NamedTemporaryFile(suffix=".sock", delete=True) as f:
        sock_path2 = f.name
    srv2 = ConnectorServer(sock_path2, _NoQuery())
    t2 = threading.Thread(target=srv2.serve_forever, daemon=True)
    t2.start()
    try:
        code, body = _post_query(sock_path2, {})
        assert code == 501
        assert body["error"] == "not_implemented"
    finally:
        srv2.shutdown()


def test_server_query_invalid_json_returns_400(stub_server) -> None:
    sock_path, _ = stub_server
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(sock_path)
    raw = b"not json"
    request = (
        f"POST /query HTTP/1.1\r\nHost: localhost\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n\r\n"
    ).encode() + raw
    sock.sendall(request)
    response = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk
    sock.close()
    header = response.split(b"\r\n\r\n")[0]
    status_code = int(header.split(b"\r\n")[0].split(b" ")[1])
    assert status_code == 400
