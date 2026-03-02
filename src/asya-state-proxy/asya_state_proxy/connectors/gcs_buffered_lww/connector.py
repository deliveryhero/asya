"""GCS buffered last-write-wins connector.

Reads configuration from environment variables:
    STATE_BUCKET            - GCS bucket name (required)
    STATE_PREFIX            - Key prefix inside the bucket (optional, default "")
    GCS_PROJECT             - GCP project ID (optional, auto-detected)
    STORAGE_EMULATOR_HOST   - Emulator endpoint for testing (optional)
"""

import io
import logging
import os
from typing import BinaryIO

from google.api_core.exceptions import NotFound
from google.cloud import storage

from asya_state_proxy.connectors._gcs_xattr import GCSXattrMixin
from asya_state_proxy.interface import KeyMeta, ListResult, StateProxyConnector


logger = logging.getLogger("asya.state-proxy")


class GCSBufferedLWW(GCSXattrMixin, StateProxyConnector):
    """Last-write-wins GCS connector. Full body is buffered in memory."""

    def __init__(self) -> None:
        bucket_name = os.environ.get("STATE_BUCKET")
        if not bucket_name:
            raise RuntimeError("STATE_BUCKET environment variable is required")

        self._prefix = os.environ.get("STATE_PREFIX", "")
        project = os.environ.get("GCS_PROJECT")

        client = storage.Client(project=project)
        self._bucket = client.bucket(bucket_name)
        self._client = client
        self._bucket_name = bucket_name
        logger.info(
            "GCSBufferedLWW connector initialised: bucket=%s prefix=%r project=%s",
            bucket_name,
            self._prefix,
            project or "(default)",
        )

    def _full_key(self, key: str) -> str:
        if self._prefix:
            return f"{self._prefix}/{key}"
        return key

    def _strip_prefix(self, full_key: str) -> str:
        """Remove the state prefix from a full GCS blob name."""
        if self._prefix and full_key.startswith(self._prefix + "/"):
            return full_key[len(self._prefix) + 1 :]
        return full_key

    def read(self, key: str) -> BinaryIO:
        """Fetch object from GCS and return as in-memory stream."""
        blob = self._bucket.blob(self._full_key(key))
        try:
            data = blob.download_as_bytes()
        except NotFound as exc:
            raise FileNotFoundError(f"Key not found: {key}") from exc
        logger.debug("read key=%s size=%d", key, len(data))
        return io.BytesIO(data)

    def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
        """Write object to GCS using last-write-wins semantics."""
        blob = self._bucket.blob(self._full_key(key))
        body = data.read()
        blob.upload_from_string(body)
        logger.debug("write key=%s size=%d", key, len(body))

    def exists(self, key: str) -> bool:
        """Return True if the object exists in GCS."""
        return self._bucket.blob(self._full_key(key)).exists()

    def stat(self, key: str) -> KeyMeta | None:
        """Return KeyMeta for the object, or None if it does not exist."""
        blob = self._bucket.blob(self._full_key(key))
        try:
            blob.reload()
        except NotFound:
            return None
        logger.debug("stat key=%s size=%d", key, blob.size)
        return KeyMeta(size=blob.size or 0, is_file=True)

    def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
        """List objects under the given prefix."""
        full_prefix = self._full_key(key_prefix) if key_prefix else (self._prefix + "/" if self._prefix else "")

        kwargs: dict = {"prefix": full_prefix}
        if delimiter:
            kwargs["delimiter"] = delimiter

        iterator = self._client.list_blobs(self._bucket_name, **kwargs)
        keys: list[str] = [self._strip_prefix(blob.name) for blob in iterator]
        prefixes: list[str] = [self._strip_prefix(p) for p in iterator.prefixes]

        logger.debug("list prefix=%r keys=%d prefixes=%d", key_prefix, len(keys), len(prefixes))
        return ListResult(keys=keys, prefixes=prefixes)

    def delete(self, key: str) -> None:
        """Delete object from GCS. Raises FileNotFoundError if it does not exist."""
        blob = self._bucket.blob(self._full_key(key))
        if not blob.exists():
            raise FileNotFoundError(f"Key not found: {key}")
        blob.delete()
        logger.debug("delete key=%s", key)
