"""Component tests: runtime <-> connector basic CRUD over Unix socket."""

import base64
import uuid

import pytest


def _key():
    """Generate a unique key to avoid test interference."""
    return f"test-{uuid.uuid4().hex[:8]}.txt"


class TestWrite:
    def test_write_text(self, runtime):
        key = _key()
        result = runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": "hello world"})
        assert result["written"] == 11

    def test_write_binary(self, runtime):
        key = _key()
        data = base64.b64encode(b"\x00\x01\x02\xff").decode()
        result = runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": data, "mode": "wb"})
        assert result["written"] == 4


class TestRead:
    def test_read_text(self, runtime):
        key = _key()
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": "hello"})
        result = runtime.invoke({"op": "read", "path": f"/state/meta/{key}"})
        assert result["content"] == "hello"

    def test_read_binary(self, runtime):
        key = _key()
        original = b"\x00\x01\x02\xff"
        encoded = base64.b64encode(original).decode()
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": encoded, "mode": "wb"})
        result = runtime.invoke({"op": "read", "path": f"/state/meta/{key}", "mode": "rb"})
        assert base64.b64decode(result["content_b64"]) == original

    def test_read_missing_key_raises_error(self, runtime):
        result = runtime.invoke_expect_error({"op": "read", "path": "/state/meta/nonexistent.txt"})
        assert "processing_error" in result.get("error", "")

    def test_write_then_overwrite(self, runtime):
        key = _key()
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": "first"})
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": "second"})
        result = runtime.invoke({"op": "read", "path": f"/state/meta/{key}"})
        assert result["content"] == "second"


class TestExists:
    def test_exists_true(self, runtime):
        key = _key()
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": "data"})
        result = runtime.invoke({"op": "exists", "path": f"/state/meta/{key}"})
        assert result["exists"] is True

    def test_exists_false(self, runtime):
        result = runtime.invoke({"op": "exists", "path": "/state/meta/does-not-exist.txt"})
        assert result["exists"] is False


class TestStat:
    def test_stat_returns_size(self, runtime):
        key = _key()
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": "12345"})
        result = runtime.invoke({"op": "stat", "path": f"/state/meta/{key}"})
        assert result["size"] == 5
        assert result["is_file"] is True

    def test_stat_missing_key_raises_error(self, runtime):
        result = runtime.invoke_expect_error({"op": "stat", "path": "/state/meta/nonexistent.txt"})
        assert "processing_error" in result.get("error", "")


class TestListdir:
    def test_listdir_returns_entries(self, runtime):
        prefix = f"listdir-{uuid.uuid4().hex[:6]}"
        runtime.invoke({"op": "write", "path": f"/state/meta/{prefix}/a.txt", "content": "a"})
        runtime.invoke({"op": "write", "path": f"/state/meta/{prefix}/b.txt", "content": "b"})
        result = runtime.invoke({"op": "listdir", "path": f"/state/meta/{prefix}"})
        assert "a.txt" in result["entries"]
        assert "b.txt" in result["entries"]

    def test_listdir_root(self, runtime):
        result = runtime.invoke({"op": "listdir", "path": "/state/meta"})
        assert isinstance(result["entries"], list)


class TestRemove:
    def test_remove_existing_key(self, runtime):
        key = _key()
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": "data"})
        result = runtime.invoke({"op": "remove", "path": f"/state/meta/{key}"})
        assert result["removed"] is True
        exists_result = runtime.invoke({"op": "exists", "path": f"/state/meta/{key}"})
        assert exists_result["exists"] is False

    def test_remove_missing_key_raises_error(self, runtime):
        result = runtime.invoke_expect_error({"op": "remove", "path": "/state/meta/nonexistent.txt"})
        assert "processing_error" in result.get("error", "")


class TestMakedirs:
    def test_makedirs_noop_for_state_paths(self, runtime):
        result = runtime.invoke({"op": "makedirs", "path": "/state/meta/some/dir", "exist_ok": True})
        assert result["created"] is True
