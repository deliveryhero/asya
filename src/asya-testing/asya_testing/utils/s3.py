"""
S3/MinIO helper functions for integration and E2E tests.

Provides utilities to validate that happy-end and error-end actors
properly persist results and errors to S3-compatible storage (MinIO).

FAIL-FAST: Required environment variables must be set by docker-compose.
"""

import json
import logging
import time
from typing import Any

import boto3
from botocore.config import Config

from asya_testing.config import require_env


logger = logging.getLogger(__name__)

S3_ENDPOINT = require_env("ASYA_S3_ENDPOINT")
S3_ACCESS_KEY = require_env("ASYA_S3_ACCESS_KEY")
S3_SECRET_KEY = require_env("ASYA_S3_SECRET_KEY")


def get_s3_client() -> Any:
    """Create S3 client configured for MinIO."""
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket_exists(bucket_name: str, max_retries: int = 3) -> None:
    """
    Ensure bucket exists, create if missing.

    Args:
        bucket_name: Bucket name to ensure exists
        max_retries: Maximum retry attempts for bucket creation
    """
    client = get_s3_client()

    for attempt in range(max_retries):
        try:
            client.head_bucket(Bucket=bucket_name)
            logger.debug(f"Bucket {bucket_name} exists (verified)")
            return
        except client.exceptions.ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "404":
                logger.info(f"Bucket {bucket_name} does not exist, creating (attempt {attempt + 1}/{max_retries})...")
                try:
                    client.create_bucket(Bucket=bucket_name)
                    logger.info(f"Bucket {bucket_name} created successfully")
                    return
                except Exception as create_error:
                    if attempt == max_retries - 1:
                        logger.error(
                            f"Failed to create bucket {bucket_name} after {max_retries} attempts: {create_error}"
                        )
                        raise
                    logger.warning(f"Bucket creation attempt {attempt + 1} failed, retrying: {create_error}")
                    import time

                    time.sleep(0.5)
            else:
                logger.error(f"Failed to check bucket {bucket_name}: {e}")
                raise


def list_objects_in_bucket(bucket_name: str, prefix: str = "") -> list[dict[str, Any]]:
    """
    List all objects in a bucket with optional prefix.

    Ensures bucket exists before listing. Creates bucket if missing.

    Args:
        bucket_name: Bucket name
        prefix: Optional prefix to filter objects

    Returns:
        List of object metadata dicts
    """
    ensure_bucket_exists(bucket_name)
    client = get_s3_client()
    try:
        response = client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
        return response.get("Contents", [])
    except Exception as e:
        logger.error(f"Failed to list objects in {bucket_name}/{prefix}: {e}")
        return []


def get_object_from_s3(bucket_name: str, key: str) -> dict[str, Any] | None:
    """
    Retrieve and parse JSON object from S3.

    Args:
        bucket_name: Bucket name
        key: Object key

    Returns:
        Parsed JSON content or None if object not found
    """
    client = get_s3_client()
    try:
        response = client.get_object(Bucket=bucket_name, Key=key)
        content = response["Body"].read().decode("utf-8")
        return json.loads(content)
    except client.exceptions.NoSuchKey:
        logger.warning(f"Object not found: s3://{bucket_name}/{key}")
        return None
    except Exception as e:
        logger.error(f"Failed to get object s3://{bucket_name}/{key}: {e}")
        return None


def find_envelope_in_s3(bucket_name: str, envelope_id: str, prefix: str = "") -> dict[str, Any] | None:
    """
    Find an envelope in S3 by ID.

    Searches through all objects in bucket matching prefix and returns
    the first object whose filename matches the envelope ID.

    Args:
        bucket_name: Bucket name
        envelope_id: Envelope ID to search for
        prefix: Optional prefix to narrow search

    Returns:
        Parsed envelope content or None if not found
    """
    objects = list_objects_in_bucket(bucket_name, prefix)
    for obj in objects:
        key = obj["Key"]
        if envelope_id in key:
            logger.info(f"Found envelope {envelope_id} at s3://{bucket_name}/{key}")
            return get_object_from_s3(bucket_name, key)

    logger.warning(f"Envelope {envelope_id} not found in bucket {bucket_name}")
    return None


def wait_for_envelope_in_s3(
    bucket_name: str,
    envelope_id: str,
    prefix: str = "",
    timeout: int = 5,
    poll_interval: float = 0.2,
) -> dict[str, Any] | None:
    """
    Wait for an envelope to appear in S3 with retry logic.

    Polls S3 bucket until envelope is found or timeout is reached.
    Avoids flaky tests by properly waiting for async S3 persistence.

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

    while time.time() - start_time < timeout:
        attempt += 1
        envelope = find_envelope_in_s3(bucket_name, envelope_id, prefix)

        if envelope is not None:
            elapsed = time.time() - start_time
            logger.info(f"Found envelope {envelope_id} in S3 after {elapsed:.2f}s ({attempt} attempts)")
            return envelope

        time.sleep(poll_interval)  # Polling interval for S3 envelope check

    logger.warning(f"Envelope {envelope_id} not found in S3 after {timeout}s ({attempt} attempts)")
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
    client = get_s3_client()
    objects = list_objects_in_bucket(bucket_name, prefix)

    if not objects:
        logger.info(f"No objects to delete in {bucket_name}/{prefix}")
        return 0

    delete_keys = [{"Key": obj["Key"]} for obj in objects]
    response = client.delete_objects(Bucket=bucket_name, Delete={"Objects": delete_keys})

    deleted_count = len(response.get("Deleted", []))
    logger.info(f"Deleted {deleted_count} objects from {bucket_name}/{prefix}")
    return deleted_count
