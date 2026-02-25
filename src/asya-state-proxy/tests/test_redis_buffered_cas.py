"""Tests for RedisBufferedCAS connector using fakeredis."""

import io

import fakeredis
import pytest
import redis as redis_lib
from asya_state_proxy.connectors.redis_buffered_cas.connector import RedisBufferedCAS
from asya_state_proxy.interface import KeyMeta


@pytest.fixture(autouse=True)
def redis_env(monkeypatch):
    """Set required environment variables for RedisBufferedCAS."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("STATE_PREFIX", raising=False)


@pytest.fixture()
def connector(monkeypatch):
    """Create a RedisBufferedCAS with fakeredis backend."""
    conn = RedisBufferedCAS()
    fake = fakeredis.FakeRedis()
    conn._redis = fake
    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_write_then_read_returns_same_data(connector):
    data = b"hello state proxy"
    connector.write("mykey", io.BytesIO(data))
    result = connector.read("mykey")
    assert result.read() == data


def test_read_missing_key_raises_file_not_found(connector):
    with pytest.raises(FileNotFoundError, match="mykey"):
        connector.read("mykey")


def test_exists_returns_true_after_write(connector):
    assert connector.exists("k") is False
    connector.write("k", io.BytesIO(b"v"))
    assert connector.exists("k") is True


def test_exists_returns_false_for_missing(connector):
    assert connector.exists("nope") is False


def test_stat_returns_key_meta_with_correct_size(connector):
    data = b"12345"
    connector.write("sized", io.BytesIO(data))
    meta = connector.stat("sized")
    assert meta is not None
    assert isinstance(meta, KeyMeta)
    assert meta.size == len(data)
    assert meta.is_file is True


def test_stat_returns_none_for_missing(connector):
    assert connector.stat("nope") is None


def test_list_returns_keys_under_prefix(connector):
    connector.write("folder/a", io.BytesIO(b"1"))
    connector.write("folder/b", io.BytesIO(b"2"))
    connector.write("other/c", io.BytesIO(b"3"))

    result = connector.list("folder/", delimiter="")
    assert "folder/a" in result.keys
    assert "folder/b" in result.keys
    assert "other/c" not in result.keys
    assert result.prefixes == []


def test_list_with_delimiter_returns_prefixes(connector):
    connector.write("dir/sub/one", io.BytesIO(b"1"))
    connector.write("dir/sub/two", io.BytesIO(b"2"))
    connector.write("dir/top", io.BytesIO(b"3"))

    result = connector.list("dir/", delimiter="/")
    assert "dir/top" in result.keys
    assert "dir/sub/" in result.prefixes
    assert "dir/sub/one" not in result.keys
    assert "dir/sub/two" not in result.keys


def test_list_empty_prefix(connector):
    connector.write("x", io.BytesIO(b"1"))
    connector.write("y", io.BytesIO(b"2"))
    result = connector.list("", delimiter="")
    assert "x" in result.keys
    assert "y" in result.keys


def test_delete_existing_key(connector):
    connector.write("todelete", io.BytesIO(b"bye"))
    connector.delete("todelete")
    assert connector.exists("todelete") is False


def test_delete_missing_key_raises_file_not_found(connector):
    with pytest.raises(FileNotFoundError):
        connector.delete("nope")


def test_write_overwrites_existing_key(connector):
    connector.write("k", io.BytesIO(b"first"))
    connector.write("k", io.BytesIO(b"second"))
    assert connector.read("k").read() == b"second"


def test_cas_conflict_raises_file_exists_error(connector):
    connector.write("k", io.BytesIO(b"v1"))

    original_pipeline = connector._redis.pipeline

    def mock_pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)

        def mock_execute(*a, **kw):
            raise redis_lib.WatchError("Watched variable changed")

        pipe.execute = mock_execute
        return pipe

    connector._redis.pipeline = mock_pipeline
    with pytest.raises(FileExistsError, match="CAS conflict"):
        connector.write("k", io.BytesIO(b"v2"))


def test_state_prefix_is_applied(monkeypatch):
    monkeypatch.setenv("STATE_PREFIX", "my-prefix")
    conn = RedisBufferedCAS()
    fake = fakeredis.FakeRedis()
    conn._redis = fake

    conn.write("foo", io.BytesIO(b"bar"))

    # Verify the full Redis key includes the prefix
    assert fake.exists("my-prefix:foo")

    # Read back via connector strips the prefix
    assert conn.read("foo").read() == b"bar"
