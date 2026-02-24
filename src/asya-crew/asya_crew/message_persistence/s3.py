"""
S3 message persistence for Asya framework.

Provides checkpoint handler for persisting complete messages to S3/MinIO.
Can be used as a hook actor (post-termination) or mid-pipeline checkpoint.

Environment Variables:
- ASYA_MSG_ROOT: Path to virtual filesystem for message metadata (default: /proc/asya/msg)
- ASYA_S3_BUCKET: S3/MinIO bucket for persistence (optional)
- ASYA_S3_ENDPOINT: MinIO endpoint (e.g., http://minio:9000, omit for AWS S3)
- ASYA_S3_ACCESS_KEY: Access key for MinIO/S3 (optional)
- ASYA_S3_SECRET_KEY: Secret key for MinIO/S3 (optional)

VFS Paths:
- /proc/asya/msg/id — read-only: message UUID
- /proc/asya/msg/route/prev — read-only: newline-separated list of processed actors
- /proc/asya/msg/status/phase — read-only: terminal phase (succeeded/failed)

Storage Prefixes:
- succeeded/ - Messages with status.phase == "succeeded"
- failed/ - Messages with status.phase == "failed"
- checkpoint/ - Messages without status.phase (mid-pipeline)

S3 Key Structure:
    {prefix}{timestamp}/{actor}/{id}.json

Examples:
    succeeded/2026-02-12T10:30:00.123456Z/text-processor/msg-123.json
    failed/2026-02-12T10:30:00.123456Z/image-analyzer/msg-456.json
    checkpoint/2026-02-12T10:30:00.123456Z/data-validator/msg-789.json

Handler Behavior:
- Persists payload to S3/MinIO with structured key path
- Returns empty dict (message passes through unchanged)
- Gracefully skips if S3 not configured (no error)
"""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")
ASYA_S3_BUCKET = os.getenv("ASYA_S3_BUCKET", "")
ASYA_S3_ENDPOINT = os.getenv("ASYA_S3_ENDPOINT", "")
ASYA_S3_ACCESS_KEY = os.getenv("ASYA_S3_ACCESS_KEY", "")
ASYA_S3_SECRET_KEY = os.getenv("ASYA_S3_SECRET_KEY", "")

s3_client = None
if ASYA_S3_BUCKET:
    try:
        import boto3

        client_kwargs = {}
        if ASYA_S3_ENDPOINT:
            client_kwargs["endpoint_url"] = ASYA_S3_ENDPOINT
            client_kwargs["aws_access_key_id"] = ASYA_S3_ACCESS_KEY or "minioadmin"
            client_kwargs["aws_secret_access_key"] = ASYA_S3_SECRET_KEY or "minioadmin"
            client_kwargs["config"] = boto3.session.Config(signature_version="s3v4")  # type: ignore[assignment,attr-defined]
            logger.info(f"MinIO persistence enabled: {ASYA_S3_ENDPOINT}/{ASYA_S3_BUCKET}")
        else:
            client_kwargs["region_name"] = os.getenv("AWS_REGION", "us-east-1")
            if ASYA_S3_ACCESS_KEY and ASYA_S3_SECRET_KEY:
                client_kwargs["aws_access_key_id"] = ASYA_S3_ACCESS_KEY
                client_kwargs["aws_secret_access_key"] = ASYA_S3_SECRET_KEY
            logger.info(f"S3 persistence enabled: {ASYA_S3_BUCKET}")

        s3_client = boto3.client("s3", **client_kwargs)  # type: ignore[call-overload]
    except ImportError:
        logger.warning("boto3 not installed, object storage persistence disabled")
        s3_client = None


def ensure_bucket_exists(bucket: str) -> None:
    """
    Ensure S3 bucket exists, creating it if necessary.

    Args:
        bucket: Bucket name to check/create

    Raises:
        Exception: If bucket cannot be created or verified
    """
    if not s3_client:
        return

    try:
        s3_client.head_bucket(Bucket=bucket)
    except Exception as e:
        error_code = e.response.get("Error", {}).get("Code") if hasattr(e, "response") else None
        http_status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode") if hasattr(e, "response") else None
        if error_code in ("404", "NoSuchBucket") or http_status == 404:
            logger.info(f"Bucket {bucket} does not exist, creating it")
            try:
                s3_client.create_bucket(Bucket=bucket)
                logger.info(f"Created bucket {bucket}")
            except Exception as create_error:
                logger.error(f"Failed to create bucket {bucket}: {create_error}")
                raise
        else:
            logger.warning(f"Could not verify bucket {bucket}: {e}")


def checkpoint_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Checkpoint handler for message persistence.

    Persists payload to S3/MinIO with structured key path. Reads message
    metadata (id, phase, actor) from the VFS at ASYA_MSG_ROOT.
    Can be used as a hook actor or mid-pipeline checkpoint.

    Args:
        payload: Message payload dict

    Returns:
        Empty dict (message passes through unchanged)

    Raises:
        ValueError: If payload is not a dict
    """
    if not isinstance(payload, dict):
        raise ValueError(f"Payload must be a dict, got {type(payload).__name__}")

    try:
        with open(f"{ASYA_MSG_ROOT}/id") as f:
            message_id = f.read().strip()
    except FileNotFoundError:
        message_id = "unknown"

    if not s3_client or not ASYA_S3_BUCKET:
        logger.debug(f"S3 persistence skipped for message {message_id}")
        return {}

    try:
        ensure_bucket_exists(ASYA_S3_BUCKET)

        try:
            with open(f"{ASYA_MSG_ROOT}/status/phase") as f:
                phase = f.read().strip()
        except FileNotFoundError:
            phase = None

        if phase == "succeeded":
            prefix = "succeeded/"
        elif phase == "failed":
            prefix = "failed/"
        else:
            prefix = "checkpoint/"

        now = datetime.now(tz=UTC)
        now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        actor = "unknown"
        try:
            with open(f"{ASYA_MSG_ROOT}/route/prev") as f:
                prev_raw = f.read().strip()
                prev_actors = [a for a in prev_raw.splitlines() if a]
                if prev_actors:
                    actor = prev_actors[-1]
        except FileNotFoundError:
            pass

        key = f"{prefix}{now_str}/{actor}/{message_id}.json"

        try:
            body = json.dumps(payload, indent=2, default=str)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize payload for message {message_id}: {e}")
            raise

        s3_client.put_object(
            Bucket=ASYA_S3_BUCKET,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )

        s3_uri = f"s3://{ASYA_S3_BUCKET}/{key}"
        logger.info(f"Persisted message {message_id} to {s3_uri}")

        return {}
    except Exception as e:
        logger.error(f"Failed to persist message {message_id} to S3: {e}", exc_info=True)
        return {}
