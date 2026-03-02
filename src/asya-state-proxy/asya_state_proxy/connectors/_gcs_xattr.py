"""Shared xattr implementation for GCS-based connectors.

All GCS connectors (buffered-cas, buffered-lww) expose the same set of metadata
attributes.  This mixin provides ``listxattr``, ``getxattr`` and ``setxattr``
so each connector only needs to inherit it.

Subclasses must provide ``self._bucket`` (google.cloud.storage.Bucket),
``self._bucket_name`` (str), and ``_full_key(key) -> str``.
"""

import os

from google.api_core.exceptions import NotFound


_GCS_ATTRS = [
    "url",
    "signed_url",
    "generation",
    "content_type",
    "storage_class",
    "metageneration",
]
_GCS_WRITABLE = {"content_type"}


class GCSXattrMixin:
    """Mixin that adds xattr support for GCS-backed connectors."""

    def listxattr(self, key: str) -> list[str]:
        return list(_GCS_ATTRS)

    def getxattr(self, key: str, attr: str) -> str:
        full_key = self._full_key(key)  # type: ignore[attr-defined]
        bucket = self._bucket  # type: ignore[attr-defined]
        bucket_name = self._bucket_name  # type: ignore[attr-defined]

        if attr == "url":
            return f"gs://{bucket_name}/{full_key}"

        if attr == "signed_url":
            ttl = int(os.environ.get("STATE_PRESIGN_TTL", "3600"))
            blob = bucket.blob(full_key)
            return blob.generate_signed_url(expiration=ttl, method="GET")

        if attr in ("generation", "content_type", "storage_class", "metageneration"):
            blob = bucket.blob(full_key)
            try:
                blob.reload()
            except NotFound as exc:
                raise FileNotFoundError(f"Key not found: {key}") from exc
            if attr == "generation":
                return str(blob.generation)
            if attr == "content_type":
                return blob.content_type or "application/octet-stream"
            if attr == "metageneration":
                return str(blob.metageneration)
            # storage_class
            return blob.storage_class or "STANDARD"

        raise KeyError(f"Unsupported attribute: {attr}")

    def setxattr(self, key: str, attr: str, value: str) -> None:
        if attr not in _GCS_WRITABLE:
            raise PermissionError(f"Attribute {attr} is read-only")

        full_key = self._full_key(key)  # type: ignore[attr-defined]
        bucket = self._bucket  # type: ignore[attr-defined]

        if attr == "content_type":
            blob = bucket.blob(full_key)
            blob.content_type = value
            blob.patch()
