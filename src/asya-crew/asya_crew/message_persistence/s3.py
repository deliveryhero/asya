"""
S3 message persistence for Asya framework.

Provides checkpoint handler for persisting complete messages to S3/MinIO.
Can be used as a hook actor (post-termination) or mid-pipeline checkpoint.

IMPORTANT: Checkpoint handlers MUST run in envelope mode (ASYA_HANDLER_MODE=envelope)
and with validation disabled (ASYA_ENABLE_VALIDATION=false).
This module will raise RuntimeError at import time if these conditions are not met.

Environment Variables:
- ASYA_HANDLER_MODE: Handler mode (MUST be "envelope")
- ASYA_ENABLE_VALIDATION: Validation flag (MUST be "false")
- ASYA_S3_BUCKET: S3/MinIO bucket for persistence (optional)
- ASYA_S3_ENDPOINT: MinIO endpoint (e.g., http://minio:9000, omit for AWS S3)
- ASYA_S3_ACCESS_KEY: Access key for MinIO/S3 (optional)
- ASYA_S3_SECRET_KEY: Secret key for MinIO/S3 (optional)

Message Structure:
    {
        "id": "<message-id>",
        "status": {
            "phase": "succeeded" | "failed" | None,
            "actor": "<actor-name>",
            ...
        },
        "route": {"actors": [...], "current": N},
        "payload": <arbitrary JSON>
    }

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
- Persists complete message to S3/MinIO
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

ASYA_HANDLER_MODE = (os.getenv("ASYA_HANDLER_MODE") or "payload").lower()
ASYA_ENABLE_VALIDATION = os.getenv("ASYA_ENABLE_VALIDATION", "true").lower() == "true"
ASYA_S3_BUCKET = os.getenv("ASYA_S3_BUCKET", "")
ASYA_S3_ENDPOINT = os.getenv("ASYA_S3_ENDPOINT", "")
ASYA_S3_ACCESS_KEY = os.getenv("ASYA_S3_ACCESS_KEY", "")
ASYA_S3_SECRET_KEY = os.getenv("ASYA_S3_SECRET_KEY", "")

if ASYA_HANDLER_MODE != "envelope":
    raise RuntimeError(
        f"Checkpoint handler must run in envelope mode. Current mode: '{ASYA_HANDLER_MODE}'. Set ASYA_HANDLER_MODE=envelope"
    )

if ASYA_ENABLE_VALIDATION:
    raise RuntimeError(
        "Checkpoint handler must run with validation disabled. Current setting: ASYA_ENABLE_VALIDATION=true. "
        "Set ASYA_ENABLE_VALIDATION=false"
    )

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


def checkpoint_handler(message: dict[str, Any]) -> dict[str, Any]:
    """
    Checkpoint handler for message persistence.

    Persists complete message to S3/MinIO with structured key path.
    Can be used as a hook actor or mid-pipeline checkpoint.

    Args:
        message: Complete message with id, route, status, payload

    Returns:
        Empty dict (message passes through unchanged)

    Raises:
        ValueError: If message is missing required field: id
    """
    if not isinstance(message, dict):
        raise ValueError(f"Message must be a dict, got {type(message).__name__}")

    if "id" not in message:
        raise ValueError("Message missing required field: id")

    message_id = message["id"]

    if not s3_client or not ASYA_S3_BUCKET:
        logger.debug(f"S3 persistence skipped for message {message_id}")
        return {}

    try:
        ensure_bucket_exists(ASYA_S3_BUCKET)

        status = message.get("status", {})
        phase = status.get("phase") if isinstance(status, dict) else None

        if phase == "succeeded":
            prefix = "succeeded/"
        elif phase == "failed":
            prefix = "failed/"
        else:
            prefix = "checkpoint/"

        now = datetime.now(tz=UTC)
        now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        actor = status.get("actor", "unknown") if isinstance(status, dict) else "unknown"
        if actor == "unknown":
            route = message.get("route", {})
            route_actors = route.get("actors", [])
            if route_actors:
                actor = route_actors[-1]

        key = f"{prefix}{now_str}/{actor}/{message_id}.json"

        try:
            body = json.dumps(message, indent=2, default=str)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize message {message_id}: {e}")
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
