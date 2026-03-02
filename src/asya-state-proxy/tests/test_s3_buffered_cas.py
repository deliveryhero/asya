"""Tests for S3BufferedCAS connector using moto mock_aws."""

import io

import boto3
import pytest
from asya_state_proxy.connectors.s3_buffered_cas.connector import S3BufferedCAS
from asya_state_proxy.interface import KeyMeta
from botocore.exceptions import ClientError
from moto import mock_aws


TEST_BUCKET = "test-state-bucket"
TEST_REGION = "us-east-1"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    """Set required environment variables for S3BufferedCAS."""
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
    return S3BufferedCAS()


# ---------------------------------------------------------------------------
# Basic read/write roundtrip tests (same as LWW)
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


def test_state_prefix_is_applied(monkeypatch, s3_bucket):
    monkeypatch.setenv("STATE_PREFIX", "my-prefix")
    conn = S3BufferedCAS()
    conn.write("foo", io.BytesIO(b"bar"))

    # Verify the full S3 key includes the prefix
    response = s3_bucket.list_objects_v2(Bucket=TEST_BUCKET, Prefix="my-prefix/")
    keys = [obj["Key"] for obj in response.get("Contents", [])]
    assert "my-prefix/foo" in keys

    # Read back via connector strips the prefix
    assert conn.read("foo").read() == b"bar"


# ---------------------------------------------------------------------------
# CAS-specific tests
# ---------------------------------------------------------------------------


def test_write_new_key_without_read_succeeds(connector):
    """Writing a brand-new key (no prior read) should succeed unconditionally."""
    connector.write("brand-new", io.BytesIO(b"first-value"))
    assert connector.read("brand-new").read() == b"first-value"


def test_write_after_read_with_no_intervening_change_succeeds(connector):
    """Read a key then write it back; ETags match so write succeeds."""
    connector.write("k", io.BytesIO(b"original"))
    connector.read("k")  # caches ETag
    connector.write("k", io.BytesIO(b"updated"))
    assert connector.read("k").read() == b"updated"


def test_write_after_external_change_raises_conflict(connector, s3_bucket):
    """Read a key, externally modify the S3 object, then write raises FileExistsError."""
    connector.write("k", io.BytesIO(b"v1"))
    connector.read("k")  # caches ETag

    # Patch put_object to simulate a 412 PreconditionFailed response when
    # IfMatch is present, as moto does not enforce conditional writes.
    original_put = connector._s3.put_object

    def mock_put(**kwargs):
        if "IfMatch" in kwargs:
            raise ClientError(
                {
                    "Error": {
                        "Code": "PreconditionFailed",
                        "Message": "At least one of the pre-conditions you specified did not hold",
                    }
                },
                "PutObject",
            )
        return original_put(**kwargs)

    connector._s3.put_object = mock_put
    with pytest.raises(FileExistsError, match="CAS conflict"):
        connector.write("k", io.BytesIO(b"v2"))


def test_write_twice_without_read_succeeds(connector):
    """Write twice without reading; second write uses ETag from first write response."""
    connector.write("k", io.BytesIO(b"first"))
    connector.write("k", io.BytesIO(b"second"))
    assert connector.read("k").read() == b"second"


def test_delete_clears_etag_cache(connector):
    """After read + delete, a subsequent write should succeed as a new key."""
    connector.write("k", io.BytesIO(b"v1"))
    connector.read("k")  # caches ETag
    connector.delete("k")  # clears ETag cache

    # Write after delete should succeed as an unconditional (new key) write.
    connector.write("k", io.BytesIO(b"v2"))
    assert connector.read("k").read() == b"v2"


def test_cas_conflict_on_stale_etag(connector, s3_bucket):
    """Simulate CAS conflict when ETag is stale."""
    connector.write("k", io.BytesIO(b"v1"))
    connector.read("k")  # caches ETag

    # Patch put_object to simulate a 412 PreconditionFailed response.
    original_put = connector._s3.put_object

    def mock_put(**kwargs):
        if "IfMatch" in kwargs:
            raise ClientError(
                {
                    "Error": {
                        "Code": "PreconditionFailed",
                        "Message": "At least one of the pre-conditions you specified did not hold",
                    }
                },
                "PutObject",
            )
        return original_put(**kwargs)

    connector._s3.put_object = mock_put
    with pytest.raises(FileExistsError, match="CAS conflict"):
        connector.write("k", io.BytesIO(b"v2"))


# ---------------------------------------------------------------------------
# xattr tests
# ---------------------------------------------------------------------------


def test_listxattr_returns_s3_attrs(connector, s3_bucket):
    connector.write("xkey", io.BytesIO(b"data"))
    attrs = connector.listxattr("xkey")
    assert "url" in attrs
    assert "presigned_url" in attrs
    assert "etag" in attrs
    assert "content_type" in attrs


def test_getxattr_url_returns_s3_uri(connector, s3_bucket):
    connector.write("xkey", io.BytesIO(b"data"))
    url = connector.getxattr("xkey", "url")
    assert url.startswith("s3://")
    assert "xkey" in url


def test_getxattr_etag_returns_string(connector, s3_bucket):
    connector.write("xkey", io.BytesIO(b"data"))
    etag = connector.getxattr("xkey", "etag")
    assert isinstance(etag, str)
    assert len(etag) > 0


def test_getxattr_content_type_returns_string(connector, s3_bucket):
    connector.write("xkey", io.BytesIO(b"data"))
    ct = connector.getxattr("xkey", "content_type")
    assert isinstance(ct, str)


def test_getxattr_unsupported_raises_key_error(connector, s3_bucket):
    connector.write("xkey", io.BytesIO(b"data"))
    with pytest.raises(KeyError):
        connector.getxattr("xkey", "nosuch")


def test_setxattr_content_type(connector, s3_bucket):
    connector.write("xkey", io.BytesIO(b"data"))
    connector.setxattr("xkey", "content_type", "text/plain")
    ct = connector.getxattr("xkey", "content_type")
    assert ct == "text/plain"


def test_setxattr_readonly_raises_permission_error(connector, s3_bucket):
    connector.write("xkey", io.BytesIO(b"data"))
    with pytest.raises(PermissionError):
        connector.setxattr("xkey", "url", "x")


def test_getxattr_etag_uses_cached_value(connector, s3_bucket):
    connector.write("cached", io.BytesIO(b"data"))
    connector.read("cached")  # populates etag cache
    etag = connector.getxattr("cached", "etag")
    assert etag == connector._etags["cached"]
