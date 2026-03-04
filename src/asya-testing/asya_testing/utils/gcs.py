"""
GCS helper functions for integration and E2E tests.

Provides utilities to validate that x-sink and x-sump actors
properly persist results and errors to GCS-compatible storage (fake-gcs-server).

FAIL-FAST: Required environment variables must be set by docker-compose.
"""

import json
import logging
import time
from typing import Any

from google.auth.credentials import AnonymousCredentials
from google.cloud import storage

from asya_testing.config import require_env


logger = logging.getLogger(__name__)

STORAGE_ENDPOINT = require_env("STORAGE_ENDPOINT")


def get_gcs_client() -> storage.Client:
    """Create GCS client configured for fake-gcs-server."""
    client = storage.Client(
        project="test",
        credentials=AnonymousCredentials(),
    )
    client._connection.API_BASE_URL = STORAGE_ENDPOINT
    return client


def ensure_bucket_exists(bucket_name: str) -> None:
    """
    Ensure bucket exists, create if missing.

    Args:
        bucket_name: Bucket name to ensure exists
    """
    client = get_gcs_client()
    bucket = client.bucket(bucket_name)

    if bucket.exists():
        logger.debug(f"Bucket {bucket_name} exists (verified)")
        return

    logger.info(f"Bucket {bucket_name} does not exist, creating...")
    client.create_bucket(bucket_name)
    logger.info(f"Bucket {bucket_name} created successfully")


def list_objects_in_bucket(bucket_name: str, prefix: str = "") -> list[storage.Blob]:
    """
    List all objects in a bucket with optional prefix.

    Ensures bucket exists before listing. Creates bucket if missing.

    Args:
        bucket_name: Bucket name
        prefix: Optional prefix to filter objects

    Returns:
        List of blob objects
    """
    ensure_bucket_exists(bucket_name)
    client = get_gcs_client()
    bucket = client.bucket(bucket_name)
    try:
        return list(bucket.list_blobs(prefix=prefix))
    except Exception as e:
        logger.error(f"Failed to list objects in gs://{bucket_name}/{prefix}: {e}")
        return []


def get_object_from_gcs(bucket_name: str, key: str) -> dict[str, Any] | None:
    """
    Retrieve and parse JSON object from GCS.

    Args:
        bucket_name: Bucket name
        key: Object key (blob name)

    Returns:
        Parsed JSON content or None if object not found
    """
    client = get_gcs_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(key)
    try:
        content = blob.download_as_text()
        return json.loads(content)
    except Exception as e:
        logger.error(f"Failed to get object gs://{bucket_name}/{key}: {e}")
        return None


def find_envelope_in_gcs(bucket_name: str, envelope_id: str, prefix: str = "") -> dict[str, Any] | None:
    """
    Find an envelope in GCS by ID.

    Searches through all objects in bucket matching prefix and returns
    the first object whose name matches the envelope ID.

    Args:
        bucket_name: Bucket name
        envelope_id: Envelope ID to search for
        prefix: Optional prefix to narrow search

    Returns:
        Parsed envelope content or None if not found
    """
    blobs = list_objects_in_bucket(bucket_name, prefix)
    for blob in blobs:
        if envelope_id in blob.name:
            logger.info(f"Found envelope {envelope_id} at gs://{bucket_name}/{blob.name}")
            return get_object_from_gcs(bucket_name, blob.name)

    logger.debug(f"Envelope {envelope_id} not found in bucket {bucket_name}")
    return None


def wait_for_envelope_in_gcs(
    bucket_name: str,
    envelope_id: str,
    prefix: str = "",
    timeout: int = 5,
    poll_interval: float = 0.2,
) -> dict[str, Any] | None:
    """
    Wait for an envelope to appear in GCS with retry logic.

    Polls GCS bucket until envelope is found or timeout is reached.

    Args:
        bucket_name: Bucket name
        envelope_id: Envelope ID to search for
        prefix: Optional prefix to narrow search
        timeout: Maximum time to wait in seconds
        poll_interval: Polling interval in seconds

    Returns:
        Parsed envelope content or None if not found within timeout
    """
    start_time = time.time()
    attempt = 0
    logger.info(f"Polling GCS for envelope {envelope_id} in {bucket_name} (timeout={timeout}s)")

    while time.time() - start_time < timeout:
        attempt += 1
        envelope = find_envelope_in_gcs(bucket_name, envelope_id, prefix)

        if envelope is not None:
            elapsed = time.time() - start_time
            logger.info(f"Found envelope {envelope_id} in GCS after {elapsed:.2f}s ({attempt} attempts)")
            return envelope

        time.sleep(poll_interval)  # Polling interval for GCS envelope check

    elapsed = time.time() - start_time
    logger.warning(f"Envelope {envelope_id} not found in GCS after {elapsed:.1f}s ({attempt} attempts)")
    return None


def delete_all_objects_in_bucket(bucket_name: str, prefix: str = "") -> int:
    """
    Delete all objects in bucket with optional prefix.

    Args:
        bucket_name: Bucket name
        prefix: Optional prefix to filter objects

    Returns:
        Number of objects deleted
    """
    blobs = list_objects_in_bucket(bucket_name, prefix)

    if not blobs:
        logger.info(f"No objects to delete in gs://{bucket_name}/{prefix}")
        return 0

    client = get_gcs_client()
    bucket = client.bucket(bucket_name)
    deleted_count = 0
    for blob in blobs:
        bucket.blob(blob.name).delete()
        deleted_count += 1

    logger.info(f"Deleted {deleted_count} objects from gs://{bucket_name}/{prefix}")
    return deleted_count
