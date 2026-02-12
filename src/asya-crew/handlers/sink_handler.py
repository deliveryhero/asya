"""
Unified sink handler for terminal message processing.

The _sink actor replaces separate happy-end and error-end actors by using
the message's status.phase field to determine behavior:
- status.phase = "succeeded" -> persists under succeeded/ prefix
- status.phase = "failed"    -> persists under failed/ prefix

The handler:
1. Reads status.phase to determine storage prefix
2. Persists the COMPLETE message to S3/MinIO (must be redrivable)
3. Returns empty dict (terminal node - sidecar reports final status to gateway)

IMPORTANT: The _sink handler MUST run in envelope mode (ASYA_HANDLER_MODE=envelope).
This module will raise RuntimeError at import time if misconfigured.

Environment Variables:
- ASYA_HANDLER_MODE: MUST be "envelope"
- ASYA_ENABLE_VALIDATION: MUST be "false"
- ASYA_S3_BUCKET: S3/MinIO bucket for persistence (optional)
- ASYA_S3_ENDPOINT: MinIO endpoint (e.g., http://minio:9000, omit for AWS S3)
- ASYA_S3_ACCESS_KEY: Access key for MinIO/S3 (optional)
- ASYA_S3_SECRET_KEY: Secret key for MinIO/S3 (optional)
"""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Configuration
ASYA_S3_BUCKET = os.getenv("ASYA_S3_BUCKET", "")
ASYA_S3_ENDPOINT = os.getenv("ASYA_S3_ENDPOINT", "")
ASYA_S3_ACCESS_KEY = os.getenv("ASYA_S3_ACCESS_KEY", "")
ASYA_S3_SECRET_KEY = os.getenv("ASYA_S3_SECRET_KEY", "")

# Defaults from asya_runtime.py:
ASYA_HANDLER_MODE = (os.getenv("ASYA_HANDLER_MODE") or "payload").lower()
ASYA_ENABLE_VALIDATION = os.getenv("ASYA_ENABLE_VALIDATION", "true").lower() == "true"

VALID_PHASES = ("succeeded", "failed")

if ASYA_HANDLER_MODE != "envelope":
    raise RuntimeError(
        f"_sink handler must run in envelope mode. Current mode: '{ASYA_HANDLER_MODE}'. Set ASYA_HANDLER_MODE=envelope"
    )

if ASYA_ENABLE_VALIDATION:
    raise RuntimeError(
        "_sink handler must run with validation disabled. Current setting: ASYA_ENABLE_VALIDATION=true. "
        "Set ASYA_ENABLE_VALIDATION=false (operator should configure this automatically)"
    )

# Optional S3 client
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
    """Ensure S3 bucket exists, creating it if necessary."""
    if not s3_client:
        return

    try:
        s3_client.head_bucket(Bucket=bucket)
    except Exception as e:
        error_code = e.response.get("Error", {}).get("Code") if hasattr(e, "response") else None
        if error_code == "404" or error_code == "NoSuchBucket" or "404" in str(e) or "Not Found" in str(e):
            logger.info(f"Bucket {bucket} does not exist, creating it")
            try:
                s3_client.create_bucket(Bucket=bucket)
                logger.info(f"Created bucket {bucket}")
            except Exception as create_error:
                logger.error(f"Failed to create bucket {bucket}: {create_error}")
                raise
        else:
            logger.warning(f"Could not verify bucket {bucket}: {e}")


def persist_to_s3(message: dict[str, Any], s3_prefix: str) -> dict[str, str]:
    """
    Persist complete message to S3/MinIO.

    Key structure: {prefix}{timestamp}/{last_actor}/{id}.json
    Example: succeeded/2025-10-16T17:30:45.123456Z/echo-actor/abc-123.json
    """
    message_id = message.get("id", "unknown")

    if not s3_client or not ASYA_S3_BUCKET:
        logger.debug(f"S3 persistence skipped for message {message_id}")
        return {}

    try:
        ensure_bucket_exists(ASYA_S3_BUCKET)

        now = datetime.now(tz=UTC)
        now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        route = message.get("route", {})
        route_actors = route.get("actors", [])
        status = message.get("status", {})
        last_actor = status.get("actor", "unknown")

        if last_actor == "unknown" and route_actors:
            last_actor = route_actors[-1]

        key = f"{s3_prefix}{now_str}/{last_actor}/{message_id}.json"

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

        return {"s3_bucket": ASYA_S3_BUCKET, "s3_key": key, "s3_uri": s3_uri}
    except Exception as e:
        logger.error(f"Failed to persist message {message_id} to S3: {e}", exc_info=True)
        return {"error": str(e)}


def sink_handler(message: dict[str, Any]) -> dict[str, Any]:
    """
    Unified terminal handler for succeeded and failed messages.

    Uses status.phase to determine the S3 storage prefix:
    - "succeeded" -> "succeeded/"
    - "failed"    -> "failed/"

    Returns empty dict - sidecar reports final status to gateway.

    Raises:
        ValueError: If message is not a dict, missing id, or has invalid/missing status.phase
    """
    if not isinstance(message, dict):
        raise ValueError(f"Message must be a dict, got {type(message).__name__}")

    if "id" not in message:
        raise ValueError("Message missing required field: id")

    status = message.get("status")
    if not isinstance(status, dict):
        raise ValueError(
            f"Message missing required field: status (got {type(status).__name__ if status is not None else 'None'})"
        )

    phase = status.get("phase")
    if phase not in VALID_PHASES:
        raise ValueError(f"Invalid status.phase: {phase!r} (expected one of {VALID_PHASES})")

    message_id = message["id"]
    s3_prefix = f"{phase}/"

    logger.info(f"Processing _sink for message {message_id} (phase={phase})")

    s3_info = persist_to_s3(message=message, s3_prefix=s3_prefix)

    logger.info(
        f"_sink processing complete for message {message_id}, S3 persisted: {bool(s3_info and 's3_uri' in s3_info)}"
    )

    return {}
