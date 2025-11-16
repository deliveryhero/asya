"""
End actor handlers.

This module provides end handlers for envelope completion:
- happy_end_handler: Processes successfully completed envelopes
- error_end_handler: Processes failed envelopes

Both handlers:
1. Persist results/errors to S3/MinIO (if configured)
2. Return S3 metadata to sidecar (for gateway reporting)

IMPORTANT: End handlers MUST run in envelope mode (ASYA_HANDLER_MODE=envelope).
This module will raise RuntimeError at import time if ASYA_HANDLER_MODE is set to "payload".

Environment Variables:
- ASYA_HANDLER_MODE: Handler mode (MUST be "envelope" for end handlers, default: envelope)
- ASYA_S3_BUCKET: S3/MinIO bucket for persistence (optional)
- ASYA_S3_ENDPOINT: MinIO endpoint (e.g., http://minio:9000, omit for AWS S3)
- ASYA_S3_ACCESS_KEY: Access key for MinIO/S3 (optional)
- ASYA_S3_SECRET_KEY: Secret key for MinIO/S3 (optional)
- ASYA_S3_RESULTS_PREFIX: Prefix for success results (default: asya-results/)
- ASYA_S3_ERRORS_PREFIX: Prefix for error results (default: asya-errors/)

Note: boto3 works with MinIO by setting ASYA_S3_ENDPOINT to MinIO URL.
Object keys are structured as: {prefix}{date}/{hour}/{last_actor}/{id}.json
Example: asya-results/2025-10-16/17/echo-actor/abc123.json

Architecture: End actors only persist to S3. The sidecar handles all
gateway communication including final status reporting.
"""

import json
import logging
import os
from datetime import datetime, timezone
from functools import partial
from typing import Any


# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Configuration
ASYA_S3_BUCKET = os.getenv("ASYA_S3_BUCKET", "")
ASYA_S3_ENDPOINT = os.getenv("ASYA_S3_ENDPOINT", "")
ASYA_S3_ACCESS_KEY = os.getenv("ASYA_S3_ACCESS_KEY", "")
ASYA_S3_SECRET_KEY = os.getenv("ASYA_S3_SECRET_KEY", "")
ASYA_S3_RESULTS_PREFIX = os.getenv("ASYA_S3_RESULTS_PREFIX", "happy-asya/")
ASYA_S3_ERRORS_PREFIX = os.getenv("ASYA_S3_ERRORS_PREFIX", "error-asya/")

# defaults from asya_runtime.py:
ASYA_HANDLER_MODE = (os.getenv("ASYA_HANDLER_MODE") or "payload").lower()
ASYA_ENABLE_VALIDATION = os.getenv("ASYA_ENABLE_VALIDATION", "true").lower() == "true"


if ASYA_HANDLER_MODE != "envelope":
    raise RuntimeError(
        f"End handlers must run in envelope mode. Current mode: '{ASYA_HANDLER_MODE}'. Set ASYA_HANDLER_MODE=envelope"
    )

if ASYA_ENABLE_VALIDATION:
    raise RuntimeError(
        "End handlers must run with validation disabled. Current setting: ASYA_ENABLE_VALIDATION=true. "
        "Set ASYA_ENABLE_VALIDATION=false (operator should configure this automatically)"
    )

# Optional dependencies
s3_client = None
if ASYA_S3_BUCKET:
    try:
        import boto3

        # Configure for MinIO or AWS S3
        client_kwargs = {}
        if ASYA_S3_ENDPOINT:
            # MinIO configuration
            client_kwargs["endpoint_url"] = ASYA_S3_ENDPOINT
            client_kwargs["aws_access_key_id"] = ASYA_S3_ACCESS_KEY or "minioadmin"
            client_kwargs["aws_secret_access_key"] = ASYA_S3_SECRET_KEY or "minioadmin"
            client_kwargs["config"] = boto3.session.Config(signature_version="s3v4")  # type: ignore[assignment,attr-defined]
            logger.info(f"MinIO persistence enabled: {ASYA_S3_ENDPOINT}/{ASYA_S3_BUCKET}")
        else:
            # AWS S3 configuration (uses IAM role or credentials from environment)
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


def persist_to_s3(envelope: dict[str, Any], s3_prefix: str) -> dict[str, str]:
    """
    Persist complete envelope to S3/MinIO with structured key path.

    Key structure: {prefix}{date}/{hour}/{last_actor}/{id}.json
    Example: asya-results/2025-10-16/17/echo-actor/abc-123.json

    Args:
        envelope: Complete envelope to persist
        s3_prefix: S3 key prefix (results or errors)
        error: Error description (for failed envelopes)

    Returns:
        Dict with S3 location info
    """
    envelope_id = envelope.get("id", "unknown")

    if not s3_client or not ASYA_S3_BUCKET:
        logger.debug(f"S3 persistence skipped for envelope {envelope_id}")
        return {}

    try:
        ensure_bucket_exists(ASYA_S3_BUCKET)

        # Build key with date/hour/last-actor structure
        now = datetime.now(tz=timezone.utc)
        now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # Find last non-end actor
        route = envelope.get("route", {})
        route_actors = route.get("actors", [])
        current_index = route.get("current")

        last_actor = "unknown"
        if route_actors:
            if current_index is not None and 0 < current_index < len(route_actors):
                # TODO: verify that: actor not in ["happy-end", "error-end"]
                last_actor = route_actors[current_index]
            else:
                last_actor = route_actors[-1]

        key = f"{s3_prefix}{now_str}/{last_actor}/{envelope_id}.json"

        # Serialize to JSON with safe handling of non-serializable types
        try:
            body = json.dumps(envelope, indent=2, default=str)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize envelope {envelope_id}: {e}")
            raise

        s3_client.put_object(
            Bucket=ASYA_S3_BUCKET,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )

        s3_uri = f"s3://{ASYA_S3_BUCKET}/{key}"
        logger.info(f"Persisted envelope {envelope_id} to {s3_uri}")

        return {"s3_bucket": ASYA_S3_BUCKET, "s3_key": key, "s3_uri": s3_uri}
    except Exception as e:
        logger.error(f"Failed to persist envelope {envelope_id} to S3: {e}", exc_info=True)
        return {"error": str(e)}


def _end_handler(envelope: dict[str, Any], s3_prefix: str, handler_type: str) -> dict[str, Any]:
    """
    Base handler for envelope completion (success or error).

    Saves the complete envelope to S3 without parsing.
    Returns empty dict - the sidecar will use the original envelope payload as the result.

    IMPORTANT: End actors are terminal - they do NOT route to any queue and do NOT
    increment route.current. They only persist the envelope and report final status.
    The sidecar's processEndActorEnvelope ignores the route in the response and
    does not send any messages to other queues.

    Args:
        envelope: Complete envelope with id, route, payload
        s3_prefix: S3 prefix for persistence (happy-asya/ or error-asya/)
        handler_type: Handler type for logging ("happy-end" or "error-end")

    Returns:
        Empty dict (end handlers must not return results)

    Raises:
        RuntimeError: If ASYA_HANDLER_MODE is not "envelope"
        ValueError: If envelope is missing required fields
    """
    if not isinstance(envelope, dict):
        raise ValueError(f"Envelope must be a dict, got {type(envelope).__name__}")

    if "id" not in envelope:
        raise ValueError("Envelope missing required field: id")

    envelope_id = envelope["id"]
    logger.info(f"Processing {handler_type} for envelope {envelope_id}")

    s3_info = persist_to_s3(envelope=envelope, s3_prefix=s3_prefix)

    logger.info(
        f"{handler_type} processing complete for envelope {envelope_id}, S3 persisted: {bool(s3_info and 's3_uri' in s3_info)}"
    )

    return {}


# Create specialized handlers using functools.partial
happy_end_handler = partial(_end_handler, s3_prefix=ASYA_S3_RESULTS_PREFIX, handler_type="happy-end")
error_end_handler = partial(_end_handler, s3_prefix=ASYA_S3_ERRORS_PREFIX, handler_type="error-end")
