"""
Generic object storage abstraction for S3 and GCS.

Provides a unified interface for object storage operations that works with both
S3/MinIO and GCS backends. The implementation delegates to backend-specific
modules (s3.py, gcs.py) based on ASYA_STORAGE environment variable.

FAIL-FAST: Required environment variables must be set by docker-compose.
"""

import logging
from dataclasses import dataclass
from typing import Any

from asya_testing.config import Storage, require_env


logger = logging.getLogger(__name__)


@dataclass
class ObjectInfo:
    """Storage object metadata."""

    key: str
    name: str


class StorageClient:
    """
    Unified storage client that delegates to S3 or GCS based on configuration.

    All operations are delegated to backend-specific helper functions in s3.py
    and gcs.py modules. This class provides only a consistent interface.
    """

    def __init__(self, storage_type: Storage):
        """
        Initialize storage client.

        Args:
            storage_type: Storage backend type (MINIO, S3, or GCS)
        """
        self.storage_type = storage_type
        logger.debug(f"Initialized StorageClient with backend: {storage_type.value}")

    @property
    def _backend(self):
        """Lazy-import the backend module matching the configured storage type."""
        if self.storage_type == Storage.GCS:
            from asya_testing.utils import gcs

            return gcs
        else:
            from asya_testing.utils import s3

            return s3

    def list_objects(self, bucket: str, prefix: str = "") -> list[ObjectInfo]:
        """
        List all objects in bucket with optional prefix.

        Args:
            bucket: Bucket name
            prefix: Optional prefix to filter objects

        Returns:
            List of ObjectInfo with key and name attributes
        """
        if self.storage_type == Storage.GCS:
            blobs = self._backend.list_objects_in_bucket(bucket, prefix)
            return [ObjectInfo(key=blob.name, name=blob.name) for blob in blobs]
        else:
            objects = self._backend.list_objects_in_bucket(bucket, prefix)
            return [ObjectInfo(key=obj["Key"], name=obj["Key"]) for obj in objects]

    def get_object_json(self, bucket: str, key: str) -> dict[str, Any] | None:
        """
        Retrieve and parse JSON object from storage.

        Args:
            bucket: Bucket name
            key: Object key

        Returns:
            Parsed JSON content or None if object not found
        """
        if self.storage_type == Storage.GCS:
            return self._backend.get_object_from_gcs(bucket, key)
        elif self.storage_type in (Storage.MINIO, Storage.S3):
            return self._backend.get_object_from_s3(bucket, key)
        else:
            raise ValueError(f"Unsupported storage type: {self.storage_type}")

    def find_by_id(self, bucket: str, envelope_id: str, prefix: str = "") -> dict[str, Any] | None:
        """
        Find an envelope in storage by ID.

        Searches through all objects in bucket matching prefix and returns
        the first object whose name contains the envelope ID.

        Args:
            bucket: Bucket name
            envelope_id: Envelope ID to search for
            prefix: Optional prefix to narrow search

        Returns:
            Parsed envelope content or None if not found
        """
        if self.storage_type == Storage.GCS:
            return self._backend.find_envelope_in_gcs(bucket, envelope_id, prefix)
        else:
            return self._backend.find_envelope_in_s3(bucket, envelope_id, prefix)

    def wait_for_object(
        self,
        bucket: str,
        envelope_id: str,
        prefix: str = "",
        timeout: int = 60,
    ) -> dict[str, Any] | None:
        """
        Wait for an envelope to appear in storage with retry logic.

        Polls storage until envelope is found or timeout is reached.

        Args:
            bucket: Bucket name
            envelope_id: Envelope ID to search for
            prefix: Optional prefix to narrow search
            timeout: Maximum time to wait in seconds

        Returns:
            Parsed envelope content or None if not found within timeout
        """
        if self.storage_type == Storage.GCS:
            return self._backend.wait_for_envelope_in_gcs(bucket, envelope_id, prefix, timeout)
        else:
            return self._backend.wait_for_envelope_in_s3(bucket, envelope_id, prefix, timeout)

    def delete_all(self, bucket: str, prefix: str = "") -> int:
        """
        Delete all objects in bucket with optional prefix.

        Args:
            bucket: Bucket name
            prefix: Optional prefix to filter objects

        Returns:
            Number of objects deleted
        """
        if self.storage_type == Storage.GCS:
            return self._backend.delete_all_objects_in_bucket(bucket, prefix)
        else:
            return self._backend.delete_all_objects_in_bucket(bucket, prefix)

    def ensure_bucket(self, bucket: str) -> None:
        """
        Ensure bucket exists, create if missing.

        Args:
            bucket: Bucket name to ensure exists
        """
        if self.storage_type == Storage.GCS:
            self._backend.ensure_bucket_exists(bucket)
        else:
            self._backend.ensure_bucket_exists(bucket)


def get_storage_client() -> StorageClient:
    """
    Create storage client based on ASYA_STORAGE environment variable.

    Returns:
        StorageClient configured for current storage backend

    Raises:
        ConfigurationError: If ASYA_STORAGE is not set or invalid
    """
    storage_str = require_env("ASYA_STORAGE", valid_values=["minio", "s3", "gcs"]).lower()
    storage_type = Storage(storage_str)
    return StorageClient(storage_type)
