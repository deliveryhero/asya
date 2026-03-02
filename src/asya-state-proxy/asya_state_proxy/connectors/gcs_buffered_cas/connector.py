"""GCS buffered compare-and-swap connector.

Uses GCS object generation numbers for optimistic concurrency control.
On read(), caches the generation. On write(), passes if_generation_match
to enforce the cached generation. If the object was modified between
read and write, GCS returns 412 Precondition Failed.

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

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage

from asya_state_proxy.connectors._gcs_xattr import GCSXattrMixin
from asya_state_proxy.interface import KeyMeta, ListResult, StateProxyConnector


logger = logging.getLogger("asya.state-proxy")


class GCSBufferedCAS(GCSXattrMixin, StateProxyConnector):
    """Compare-and-swap GCS connector using generation-based preconditions.

    Maintains an in-memory generation cache to detect concurrent modifications.
    When writing a key that was previously read, the write is conditional
    on the cached generation matching the current GCS generation. If the object
    was modified externally, the write raises FileExistsError.
    """

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
        self._generations: dict[str, int] = {}
        logger.info(
            "GCSBufferedCAS connector initialised: bucket=%s prefix=%r project=%s",
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
        """Fetch object from GCS, cache generation, and return as in-memory stream."""
        blob = self._bucket.blob(self._full_key(key))
        try:
            data = blob.download_as_bytes()
        except NotFound as exc:
            raise FileNotFoundError(f"Key not found: {key}") from exc
        self._generations[key] = blob.generation
        logger.debug("read key=%s size=%d generation=%d", key, len(data), blob.generation)
        return io.BytesIO(data)

    def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
        """Write object to GCS with CAS semantics when a prior generation is cached.

        If the key was previously read, the write is conditional on the cached
        generation matching the current GCS object generation. If the condition
        fails (object was modified externally), FileExistsError is raised.

        If the key has never been read, the write is unconditional (new key path).
        """
        blob = self._bucket.blob(self._full_key(key))
        body = data.read()

        cached_gen = self._generations.get(key)
        try:
            blob.upload_from_string(body, if_generation_match=cached_gen)
        except PreconditionFailed as exc:
            raise FileExistsError(f"CAS conflict: key={key} cached_generation={cached_gen}") from exc

        # Fetch the new generation for subsequent CAS writes
        blob.reload()
        self._generations[key] = blob.generation
        logger.debug("write key=%s size=%d generation=%d", key, len(body), blob.generation)

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

    def getxattr(self, key: str, attr: str) -> str:
        """Override to return cached generation when available."""
        if attr == "generation" and key in self._generations:
            return str(self._generations[key])
        return super().getxattr(key, attr)

    def delete(self, key: str) -> None:
        """Delete object from GCS and clear generation cache. Raises FileNotFoundError if not found."""
        blob = self._bucket.blob(self._full_key(key))
        if not blob.exists():
            raise FileNotFoundError(f"Key not found: {key}")
        blob.delete()
        self._generations.pop(key, None)
        logger.debug("delete key=%s", key)
