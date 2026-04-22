import json


def test_healthz(proxy):
    resp = proxy.request("GET", "/healthz")
    assert resp.status == 200


def test_write_and_read(proxy):
    doc = {"status": "running", "actor": "train-model", "progress": 42.0}
    resp = proxy.request("PUT", "/keys/test-msg-001", doc)
    assert resp.status == 204

    resp = proxy.request("GET", "/keys/test-msg-001")
    assert resp.status == 200
    row = json.loads(resp.read())
    assert row["key"] == "test-msg-001"
    assert row["value"]["status"] == "running"
    assert row["value"]["progress"] == 42.0
    # _ca/_ua must not leak into the returned value
    assert "_ca" not in row["value"]
    assert "_ua" not in row["value"]
    # timestamps must be present in the row
    assert row["created_at"]
    assert row["updated_at"]


def test_read_not_found(proxy):
    resp = proxy.request("GET", "/keys/does-not-exist-xyz")
    assert resp.status == 404


def test_head_exists(proxy):
    proxy.request("PUT", "/keys/test-head-001", {"status": "pending"})
    resp = proxy.request("HEAD", "/keys/test-head-001")
    assert resp.status == 200


def test_head_missing(proxy):
    resp = proxy.request("HEAD", "/keys/test-head-missing-xyz")
    assert resp.status == 404


def test_delete(proxy):
    proxy.request("PUT", "/keys/test-del-001", {"status": "failed"})
    resp = proxy.request("DELETE", "/keys/test-del-001")
    assert resp.status == 204

    resp = proxy.request("GET", "/keys/test-del-001")
    assert resp.status == 404


def test_delete_not_found(proxy):
    resp = proxy.request("DELETE", "/keys/test-del-missing-xyz")
    assert resp.status == 404


def test_overwrite_preserves_created_at(proxy):
    proxy.request("PUT", "/keys/test-overwrite-001", {"status": "pending"})

    resp = proxy.request("GET", "/keys/test-overwrite-001")
    row1 = json.loads(resp.read())
    created_at_before = row1["created_at"]

    proxy.request("PUT", "/keys/test-overwrite-001", {"status": "running"})

    resp = proxy.request("GET", "/keys/test-overwrite-001")
    row2 = json.loads(resp.read())
    assert row2["created_at"] == created_at_before, "created_at must survive overwrites"
    assert row2["value"]["status"] == "running"


def test_conditional_write_match(proxy):
    proxy.request("PUT", "/keys/test-cond-001", {"status": "pending"})

    resp = proxy.request("PUT", "/keys/test-cond-001?if_status=pending", {"status": "running"})
    assert resp.status == 204

    resp = proxy.request("GET", "/keys/test-cond-001")
    row = json.loads(resp.read())
    assert row["value"]["status"] == "running"


def test_conditional_write_mismatch(proxy):
    proxy.request("PUT", "/keys/test-cond-002", {"status": "running"})

    resp = proxy.request("PUT", "/keys/test-cond-002?if_status=pending", {"status": "succeeded"})
    assert resp.status == 409


def test_list_keys(proxy):
    proxy.request("PUT", "/keys/list-a", {"x": 1})
    proxy.request("PUT", "/keys/list-b", {"x": 2})
    proxy.request("PUT", "/keys/other-c", {"x": 3})

    resp = proxy.request("GET", "/keys/?prefix=list-")
    assert resp.status == 200
    data = json.loads(resp.read())
    keys = data["keys"]
    assert "list-a" in keys
    assert "list-b" in keys
    assert "other-c" not in keys
