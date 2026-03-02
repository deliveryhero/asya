"""Tests for GCSBufferedLWW connector using unittest.mock."""

import io
from unittest.mock import MagicMock, patch

import pytest
from asya_state_proxy.connectors.gcs_buffered_lww.connector import GCSBufferedLWW
from asya_state_proxy.interface import KeyMeta
from google.api_core.exceptions import NotFound


TEST_BUCKET = "test-state-bucket"


@pytest.fixture(autouse=True)
def gcs_env(monkeypatch):
    """Set required environment variables for GCSBufferedLWW."""
    monkeypatch.setenv("STATE_BUCKET", TEST_BUCKET)
    monkeypatch.delenv("STATE_PREFIX", raising=False)
    monkeypatch.delenv("GCS_PROJECT", raising=False)
    monkeypatch.delenv("STORAGE_EMULATOR_HOST", raising=False)


@pytest.fixture()
def mock_client():
    """Create a mock GCS client with bucket and blob support."""
    with patch("asya_state_proxy.connectors.gcs_buffered_lww.connector.storage.Client") as mock_cls:
        client = MagicMock()
        bucket = MagicMock()
        client.bucket.return_value = bucket
        mock_cls.return_value = client

        # Store for easy access in tests
        client._mock_bucket = bucket
        client._blobs = {}

        def make_blob(name):
            if name not in client._blobs:
                blob = MagicMock()
                blob.name = name
                blob.size = 0
                blob.generation = 1
                blob.metageneration = 1
                blob.content_type = "application/octet-stream"
                blob.storage_class = "STANDARD"
                blob._data = None
                blob._exists = False

                def download_as_bytes(**kwargs):
                    if not blob._exists:
                        raise NotFound("not found")
                    return blob._data

                def upload_from_string(data, **kwargs):
                    blob._data = data if isinstance(data, bytes) else data.encode()
                    blob._exists = True
                    blob.size = len(blob._data)
                    blob.generation += 1

                def exists(**kwargs):
                    return blob._exists

                def reload(**kwargs):
                    if not blob._exists:
                        raise NotFound("not found")

                def delete(**kwargs):
                    blob._exists = False
                    blob._data = None

                def patch_blob(**kwargs):
                    pass

                blob.download_as_bytes = download_as_bytes
                blob.upload_from_string = upload_from_string
                blob.exists = exists
                blob.reload = reload
                blob.delete = delete
                blob.patch = patch_blob
                client._blobs[name] = blob
            return client._blobs[name]

        bucket.blob = make_blob

        def list_blobs(bucket_name, prefix="", delimiter=None):
            matching = []
            prefixes_set = set()
            for name, blob in client._blobs.items():
                if blob._exists and name.startswith(prefix):
                    if delimiter:
                        rest = name[len(prefix) :]
                        if delimiter in rest:
                            pfx = prefix + rest[: rest.index(delimiter) + 1]
                            prefixes_set.add(pfx)
                            continue
                    matching.append(blob)

            iterator = iter(matching)
            result = MagicMock(wraps=iterator)
            result.__iter__ = lambda self: iter(matching)
            result.prefixes = prefixes_set
            return result

        client.list_blobs = list_blobs
        yield client


@pytest.fixture()
def connector(mock_client):
    return GCSBufferedLWW()


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


def test_write_overwrites_existing_key_lww(connector):
    connector.write("k", io.BytesIO(b"first"))
    connector.write("k", io.BytesIO(b"second"))
    assert connector.read("k").read() == b"second"


def test_state_prefix_is_applied(monkeypatch, mock_client):
    monkeypatch.setenv("STATE_PREFIX", "my-prefix")
    conn = GCSBufferedLWW()
    conn.write("foo", io.BytesIO(b"bar"))

    # Verify the blob was created with the prefixed name
    assert "my-prefix/foo" in mock_client._blobs
    assert mock_client._blobs["my-prefix/foo"]._exists

    # Read back via connector strips the prefix
    assert conn.read("foo").read() == b"bar"


# ---------------------------------------------------------------------------
# xattr tests
# ---------------------------------------------------------------------------


def test_listxattr_returns_gcs_attrs(connector):
    connector.write("xkey", io.BytesIO(b"data"))
    attrs = connector.listxattr("xkey")
    assert "url" in attrs
    assert "signed_url" in attrs
    assert "generation" in attrs
    assert "content_type" in attrs
    assert "metageneration" in attrs
    assert "storage_class" in attrs


def test_getxattr_url_returns_gs_uri(connector):
    connector.write("xkey", io.BytesIO(b"data"))
    url = connector.getxattr("xkey", "url")
    assert url.startswith("gs://")
    assert "xkey" in url


def test_getxattr_content_type_returns_string(connector):
    connector.write("xkey", io.BytesIO(b"data"))
    ct = connector.getxattr("xkey", "content_type")
    assert isinstance(ct, str)


def test_getxattr_unsupported_raises_key_error(connector):
    connector.write("xkey", io.BytesIO(b"data"))
    with pytest.raises(KeyError):
        connector.getxattr("xkey", "nosuch")


def test_setxattr_content_type(connector):
    connector.write("xkey", io.BytesIO(b"data"))
    connector.setxattr("xkey", "content_type", "text/plain")
    # Verify patch was called on the blob
    blob = connector._bucket.blob("xkey")
    assert blob.content_type == "text/plain"


def test_setxattr_readonly_raises_permission_error(connector):
    connector.write("xkey", io.BytesIO(b"data"))
    with pytest.raises(PermissionError):
        connector.setxattr("xkey", "url", "x")
