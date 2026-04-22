import json


def _seed(proxy, docs: dict):
    for key, doc in docs.items():
        resp = proxy.request("PUT", f"/keys/{key}", doc)
        assert resp.status == 204, f"seed {key}: got {resp.status}"


def test_query_filter_eq(proxy):
    _seed(proxy, {
        "q-eq-1": {"status": "running", "actor": "train"},
        "q-eq-2": {"status": "succeeded", "actor": "eval"},
        "q-eq-3": {"status": "running", "actor": "deploy"},
    })
    resp = proxy.request("POST", "/query", {"prefix": "q-eq-", "filter": {"status": "running"}})
    assert resp.status == 200
    data = json.loads(resp.read())
    keys = [r["key"] for r in (data["rows"] or [])]
    assert "q-eq-1" in keys
    assert "q-eq-3" in keys
    assert "q-eq-2" not in keys


def test_query_filter_gt(proxy):
    _seed(proxy, {
        "q-gt-1": {"status": "running", "progress": 30},
        "q-gt-2": {"status": "running", "progress": 70},
        "q-gt-3": {"status": "running", "progress": 90},
    })
    resp = proxy.request("POST", "/query", {
        "prefix": "q-gt-",
        "filter": {"progress": {"$gt": 50}},
    })
    assert resp.status == 200
    data = json.loads(resp.read())
    keys = [r["key"] for r in (data["rows"] or [])]
    assert "q-gt-2" in keys
    assert "q-gt-3" in keys
    assert "q-gt-1" not in keys


def test_query_sort_and_limit(proxy):
    _seed(proxy, {
        "q-sl-1": {"status": "running", "progress": 10},
        "q-sl-2": {"status": "running", "progress": 50},
        "q-sl-3": {"status": "running", "progress": 90},
    })
    resp = proxy.request("POST", "/query", {
        "prefix": "q-sl-",
        "sort": ["-progress"],
        "limit": 2,
    })
    assert resp.status == 200
    data = json.loads(resp.read())
    rows = data["rows"] or []
    assert len(rows) == 2
    # total is pre-limit count; rows is the paginated slice.
    assert data["total"] == 3
    assert rows[0]["value"]["progress"] == 90


def test_query_empty_prefix(proxy):
    resp = proxy.request("POST", "/query", {
        "prefix": "no-match-xyzzy-",
        "filter": {"status": "running"},
    })
    assert resp.status == 200
    data = json.loads(resp.read())
    assert data["total"] == 0
    assert not data.get("rows")


def test_query_nin(proxy):
    _seed(proxy, {
        "q-nin-1": {"status": "succeeded"},
        "q-nin-2": {"status": "failed"},
        "q-nin-3": {"status": "running"},
    })
    resp = proxy.request("POST", "/query", {
        "prefix": "q-nin-",
        "filter": {"status": {"$nin": ["succeeded", "failed", "canceled"]}},
    })
    assert resp.status == 200
    data = json.loads(resp.read())
    keys = [r["key"] for r in (data["rows"] or [])]
    assert "q-nin-3" in keys
    assert "q-nin-1" not in keys
    assert "q-nin-2" not in keys


def test_query_exists(proxy):
    _seed(proxy, {
        "q-ex-1": {"status": "running", "deadline_at": "2026-04-22T12:00:00Z"},
        "q-ex-2": {"status": "running"},
    })
    resp = proxy.request("POST", "/query", {
        "prefix": "q-ex-",
        "filter": {"deadline_at": {"$exists": True}},
    })
    assert resp.status == 200
    data = json.loads(resp.read())
    keys = [r["key"] for r in (data["rows"] or [])]
    assert "q-ex-1" in keys
    assert "q-ex-2" not in keys


def test_query_value_no_meta_fields(proxy):
    _seed(proxy, {"q-meta-1": {"status": "pending", "actor": "check"}})
    resp = proxy.request("POST", "/query", {"prefix": "q-meta-1"})
    assert resp.status == 200
    data = json.loads(resp.read())
    rows = data.get("rows") or []
    for row in rows:
        assert "_ca" not in row["value"], "_ca must not appear in query row value"
        assert "_ua" not in row["value"], "_ua must not appear in query row value"
