"""Component tests for POST /query on S3/GCS connectors (DuckDB httpfs).

These tests write JSON documents via the runtime (state proxy path), then call
POST /query directly on the connector socket to verify Mango-style filtering.

Profiles that support /query: s3-lww, gcs-lww (ObjectStoreQueryMixin).
All other profiles receive 501 and are skipped automatically.
"""

import json
import uuid

import pytest


def _run_id() -> str:
    return f"qtest-{uuid.uuid4().hex[:8]}"


def _write_doc(runtime, prefix: str, name: str, doc: dict) -> None:
    """Write a JSON document to the state proxy via the runtime."""
    runtime.invoke(
        {
            "op": "write",
            "path": f"/state/meta/{prefix}{name}.json",
            "content": json.dumps(doc),
        }
    )


@pytest.fixture(autouse=True)
def require_query_support(connector_client, connector_profile):
    """Skip the entire module if this connector profile doesn't support /query."""
    status, body = connector_client.post_query({})
    if status == 501:
        pytest.skip(f"profile {connector_profile!r} does not support /query")


class TestQueryBasic:
    def test_empty_prefix_returns_result(self, connector_client):
        status, body = connector_client.post_query({})
        assert status == 200
        assert "rows" in body
        assert "total" in body

    def test_filter_by_field(self, runtime, connector_client):
        prefix = f"{_run_id()}/"
        _write_doc(runtime, prefix, "done1", {"status": "done", "model": "sdxl"})
        _write_doc(runtime, prefix, "done2", {"status": "done", "model": "sd15"})
        _write_doc(runtime, prefix, "run1", {"status": "running", "model": "sdxl"})

        status, body = connector_client.post_query(
            {"prefix": prefix, "filter": {"status": "done"}}
        )
        assert status == 200
        assert body["total"] == 2
        for row in body["rows"]:
            assert row["status"] == "done"

    def test_prefix_scopes_results(self, runtime, connector_client):
        run = _run_id()
        prefix_a = f"{run}/a/"
        prefix_b = f"{run}/b/"
        _write_doc(runtime, prefix_a, "doc1", {"tag": "a"})
        _write_doc(runtime, prefix_b, "doc2", {"tag": "b"})

        status, body = connector_client.post_query({"prefix": prefix_a})
        assert status == 200
        assert body["total"] == 1
        assert body["rows"][0]["tag"] == "a"

    def test_limit_respected(self, runtime, connector_client):
        prefix = f"{_run_id()}/"
        for i in range(5):
            _write_doc(runtime, prefix, f"item{i}", {"n": i})

        status, body = connector_client.post_query({"prefix": prefix, "limit": 2})
        assert status == 200
        assert len(body["rows"]) == 2
        assert body["total"] == 5

    def test_sort_ascending(self, runtime, connector_client):
        prefix = f"{_run_id()}/"
        for name in ("c", "a", "b"):
            _write_doc(runtime, prefix, f"doc-{name}", {"name": name})

        status, body = connector_client.post_query({"prefix": prefix, "sort": ["name"]})
        assert status == 200
        names = [r["name"] for r in body["rows"]]
        assert names == sorted(names)

    def test_sort_descending(self, runtime, connector_client):
        prefix = f"{_run_id()}/"
        for name in ("c", "a", "b"):
            _write_doc(runtime, prefix, f"doc-{name}", {"name": name})

        status, body = connector_client.post_query(
            {"prefix": prefix, "sort": ["-name"]}
        )
        assert status == 200
        names = [r["name"] for r in body["rows"]]
        assert names == sorted(names, reverse=True)

    def test_no_match_returns_empty(self, runtime, connector_client):
        prefix = f"{_run_id()}/"
        _write_doc(runtime, prefix, "doc", {"status": "done"})

        status, body = connector_client.post_query(
            {"prefix": prefix, "filter": {"status": "nonexistent"}}
        )
        assert status == 200
        assert body["total"] == 0
        assert body["rows"] == []

    def test_empty_prefix_returns_404_not_error(self, connector_client):
        """An S3 prefix with no matching objects returns empty, not 500."""
        nonexistent = f"nonexistent-{uuid.uuid4().hex}/"
        status, body = connector_client.post_query({"prefix": nonexistent})
        assert status == 200
        assert body["total"] == 0


class TestQueryValidation:
    def test_invalid_filter_field_returns_400(self, connector_client):
        status, body = connector_client.post_query(
            {"filter": {"bad field!": "x"}}
        )
        assert status == 400

    def test_filter_must_be_object(self, connector_client):
        status, body = connector_client.post_query({"filter": "not-a-dict"})
        assert status == 400
        assert body["error"] == "bad_request"

    def test_sort_must_be_array(self, connector_client):
        status, body = connector_client.post_query({"sort": "name"})
        assert status == 400
        assert body["error"] == "bad_request"

    def test_negative_limit_returns_400(self, connector_client):
        status, body = connector_client.post_query({"limit": -1})
        assert status == 400

    def test_negative_offset_returns_400(self, connector_client):
        status, body = connector_client.post_query({"offset": -5})
        assert status == 400
