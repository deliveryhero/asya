"""Tests for S3Passthrough connector using moto mock_aws."""

import io

import boto3
import pytest
from asya_state_proxy.connectors.s3_passthrough.connector import S3Passthrough, _StreamingBodyWrapper
from asya_state_proxy.interface import KeyMeta
from moto import mock_aws


TEST_BUCKET = "test-state-bucket"
TEST_REGION = "us-east-1"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    """Set required environment variables for S3Passthrough."""
    monkeypatch.setenv("STATE_BUCKET", TEST_BUCKET)
    monkeypatch.setenv("AWS_REGION", TEST_REGION)
    monkeypatch.delenv("STATE_PREFIX", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    # moto requires fake credentials
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")


@pytest.fixture()
def s3_bucket():
    """Create a mock S3 bucket and yield."""
    with mock_aws():
        client = boto3.client("s3", region_name=TEST_REGION)
        client.create_bucket(Bucket=TEST_BUCKET)
        yield client


@pytest.fixture()
def connector(s3_bucket):
    return S3Passthrough()


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


def test_state_prefix_is_applied(monkeypatch, s3_bucket):
    monkeypatch.setenv("STATE_PREFIX", "my-prefix")
    conn = S3Passthrough()
    conn.write("foo", io.BytesIO(b"bar"))

    # Verify the full S3 key includes the prefix
    response = s3_bucket.list_objects_v2(Bucket=TEST_BUCKET, Prefix="my-prefix/")
    keys = [obj["Key"] for obj in response.get("Contents", [])]
    assert "my-prefix/foo" in keys

    # Read back via connector strips the prefix
    assert conn.read("foo").read() == b"bar"


def test_read_streams_without_full_buffer(connector):
    """Verify read() returns a streaming wrapper, not a BytesIO buffer."""
    data = b"streaming content"
    connector.write("stream-key", io.BytesIO(data))
    result = connector.read("stream-key")
    assert isinstance(result, _StreamingBodyWrapper)
    assert result.read() == data
