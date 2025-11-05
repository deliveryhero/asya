"""
Terminal actor handlers.

This module provides terminal handlers for job completion:
- happy_end_handler: Processes successfully completed jobs
- error_end_handler: Processes failed jobs

Both handlers:
1. Persist results/errors to S3/MinIO (if configured)
2. Report final status to gateway (if configured)
3. Return empty dict to signal terminal processing

Environment Variables:
- ASYA_GATEWAY_URL: Gateway HTTP endpoint (optional, e.g., http://gateway:8080)
- ASYA_S3_BUCKET: S3/MinIO bucket for persistence (optional)
- ASYA_S3_ENDPOINT: MinIO endpoint (e.g., http://minio:9000, omit for AWS S3)
- ASYA_S3_ACCESS_KEY: Access key for MinIO/S3 (optional)
- ASYA_S3_SECRET_KEY: Secret key for MinIO/S3 (optional)
- ASYA_S3_RESULTS_PREFIX: Prefix for success results (default: asya-results/)
- ASYA_S3_ERRORS_PREFIX: Prefix for error results (default: asya-errors/)
- ASYA_DLQ_NAME: Dead letter queue name (default: dead-letter-queue)

Note: boto3 works with MinIO by setting ASYA_S3_ENDPOINT to MinIO URL.
Object keys are structured as: {prefix}{date}/{hour}/{last_step}/{job_id}.json
Example: asya-results/2025-10-16/17/echo-actor/abc123.json
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
ASYA_GATEWAY_URL = os.getenv("ASYA_GATEWAY_URL", "")
ASYA_DLQ_NAME = os.getenv("ASYA_DLQ_NAME", "dead-letter-queue")
ASYA_S3_BUCKET = os.getenv("ASYA_S3_BUCKET", "")
ASYA_S3_ENDPOINT = os.getenv("ASYA_S3_ENDPOINT", "")
ASYA_S3_ACCESS_KEY = os.getenv("ASYA_S3_ACCESS_KEY", "")
ASYA_S3_SECRET_KEY = os.getenv("ASYA_S3_SECRET_KEY", "")
ASYA_S3_RESULTS_PREFIX = os.getenv("ASYA_S3_RESULTS_PREFIX", "asya-results/")
ASYA_S3_ERRORS_PREFIX = os.getenv("ASYA_S3_ERRORS_PREFIX", "asya-errors/")

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
            client_kwargs["config"] = boto3.session.Config(signature_version="s3v4")
            logger.info(
                f"MinIO persistence enabled: {ASYA_S3_ENDPOINT}/{ASYA_S3_BUCKET}"
            )
        else:
            # AWS S3 configuration (uses IAM role or credentials from environment)
            client_kwargs["region_name"] = os.getenv("AWS_REGION", "us-east-1")
            if ASYA_S3_ACCESS_KEY and ASYA_S3_SECRET_KEY:
                client_kwargs["aws_access_key_id"] = ASYA_S3_ACCESS_KEY
                client_kwargs["aws_secret_access_key"] = ASYA_S3_SECRET_KEY
            logger.info(f"S3 persistence enabled: {ASYA_S3_BUCKET}")

        s3_client = boto3.client("s3", **client_kwargs)
    except ImportError:
        logger.warning("boto3 not installed, object storage persistence disabled")
        s3_client = None

requests = None
if ASYA_GATEWAY_URL:
    try:
        import requests as requests_module

        requests = requests_module
        logger.info(f"Gateway reporting enabled: {ASYA_GATEWAY_URL}")
    except ImportError:
        logger.warning("requests not installed, gateway reporting disabled")
        requests = None


def parse_error_message(msg: Dict[str, Any]) -> tuple[str, Dict[str, Any], str]:
    """
    Parse error message which may be wrapped.

    Returns:
        (job_id, original_payload, error_description)

    Raises:
        ValueError: If job_id is not present as top-level key
    """
    # Check if this is wrapped error format: {"error": "...", "original_message": "..."}
    error_desc = msg.get("error", "Unknown error")
    original_msg = msg

    if "original_message" in msg and isinstance(msg["original_message"], str):
        try:
            original_msg = json.loads(msg["original_message"])
        except json.JSONDecodeError:
            logger.warning(
                f"Failed to parse original_message: {msg['original_message'][:100]}"
            )

    # Require job_id as top-level key (strict schema)
    job_id = original_msg.get("job_id")
    if not job_id:
        raise ValueError("Missing required message key: job_id")

    payload = original_msg.get("payload", {})

    return job_id, payload, error_desc


def persist_to_s3(
    job_id: str,
    data: Dict[str, Any],
    status: str,
    s3_prefix: str,
    route_steps: Optional[list] = None,
    current_index: Optional[int] = None,
    error: Optional[str] = None,
) -> Dict[str, str]:
    """
    Persist result or error to S3/MinIO with structured key path.

    Key structure: {prefix}{date}/{hour}/{last_step}/{job_id}.json
    Example: asya-results/2025-10-16/17/echo-actor/abc-123.json

    Args:
        job_id: Job identifier
        data: Job result payload or error payload
        status: Job status ("succeeded" or "failed")
        s3_prefix: S3 key prefix (results or errors)
        route_steps: Route steps list to determine last step
        current_index: Current step index (terminal queue index)
        error: Error description (for failed jobs)

    Returns:
        Dict with S3 location info
    """
    if not s3_client or not ASYA_S3_BUCKET:
        logger.debug(f"S3 persistence skipped for job {job_id}")
        return {}

    try:
        # Build key with date/hour/last-step structure
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        hour_str = now.strftime("%H")

        # Find last non-terminal step
        last_step = "unknown"
        if route_steps and current_index is not None and current_index > 0:
            last_step = route_steps[current_index - 1]
        else:
            last_step = route_steps[-1] if route_steps else "unknown"

        key = f"{s3_prefix}{date_str}/{hour_str}/{last_step}/{job_id}.json"

        # Build JSON body
        body_data = {
            "job_id": job_id,
            "route_steps": route_steps,
            "last_step": last_step,
            "timestamp": now.isoformat(),
            "status": status,
        }

        if status == "succeeded":
            body_data["result"] = data
        else:  # failed
            body_data["error"] = error
            body_data["payload"] = data

        body = json.dumps(body_data, indent=2)

        s3_client.put_object(
            Bucket=ASYA_S3_BUCKET,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )

        s3_uri = f"s3://{ASYA_S3_BUCKET}/{key}"
        logger.info(f"Persisted job {job_id} ({status}) to {s3_uri}")

        return {"s3_bucket": ASYA_S3_BUCKET, "s3_key": key, "s3_uri": s3_uri}
    except Exception as e:
        logger.error(f"Failed to persist job {job_id} to S3: {e}", exc_info=True)
        return {"error": str(e)}


def report_to_gateway(
    job_id: str,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    progress: Optional[float] = None,
    s3_info: Optional[Dict[str, str]] = None,
) -> bool:
    """
    Report final status to gateway via HTTP.

    Args:
        job_id: Job identifier
        status: Job status ("succeeded" or "failed")
        result: Job result (for successful jobs)
        error: Error description (for failed jobs)
        progress: Progress percentage (1.0 for success, None for failure)
        s3_info: S3 persistence metadata

    Returns:
        True if reported successfully (or gateway not configured), False on error
    """
    if not requests or not ASYA_GATEWAY_URL:
        logger.debug(f"Gateway reporting skipped for job {job_id}")
        return True

    try:
        url = f"{ASYA_GATEWAY_URL}/jobs/{job_id}/final"
        payload = {
            "job_id": job_id,
            "status": status,
            "progress": progress,
            "metadata": s3_info or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if status == "succeeded":
            payload["result"] = result
        else:  # failed
            payload["error"] = error

        response = requests.post(url, json=payload, timeout=5)

        if response.status_code in (200, 201, 204):
            logger.info(f"Reported job {job_id} {status} to gateway")
            return True
        else:
            logger.warning(
                f"Gateway returned non-success status for job {job_id}: "
                f"{response.status_code} - {response.text[:200]}"
            )
            return False
    except requests.exceptions.Timeout:
        logger.warning(f"Gateway timeout for job {job_id} (continuing anyway)")
        return False
    except Exception as e:
        logger.error(f"Failed to report job {job_id} to gateway: {e}")
        return False


def happy_end_handler(msg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle successfully completed jobs.

    Message format:
    {
        "job_id": "...",
        "route": {
            "steps": ["queue1", "queue2", ...],
            "current": N,
            "metadata": {...}
        },
        "payload": {...}  # Result from actor
    }

    Returns:
        Empty dict (terminal - no further routing)
    """
    # Extract job information (strict schema: job_id must be top-level)
    job_id = msg.get("job_id")
    if not job_id:
        raise ValueError("Missing required message key: job_id")

    payload = msg.get("payload", {})
    route = msg.get("route", {})
    route_steps = route.get("steps", [])
    current_index = route.get("current")

    logger.info(f"Processing successful completion for job {job_id}")

    # Persist to S3/MinIO (if enabled)
    s3_info = persist_to_s3(
        job_id=job_id,
        data=payload,
        status="succeeded",
        s3_prefix=ASYA_S3_RESULTS_PREFIX,
        route_steps=route_steps,
        current_index=current_index,
    )

    # Report to gateway (if enabled)
    gateway_reported = report_to_gateway(
        job_id=job_id,
        status="succeeded",
        result=payload,
        progress=1.0,
        s3_info=s3_info,
    )

    # Log summary
    summary = {
        "job_id": job_id,
        "status": "processed",
        "s3_persisted": bool(s3_info and "s3_uri" in s3_info),
        "gateway_reported": gateway_reported,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if s3_info:
        summary["s3_info"] = s3_info

    logger.info(f"Happy-end processing complete for job {job_id}: {summary}")

    # Return empty dict (sidecar will discard in terminal mode)
    return {}


def error_end_handler(msg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle failed jobs.

    Message format:
    {
        "error": "error description",
        "original_message": "{...}"  # JSON string of original message
    }
    OR
    {
        "job_id": "...",
        "route": {...},
        "payload": {...}
    }

    Returns:
        Empty dict (terminal processing - sidecar sends to DLQ)
    """
    # Parse error message (validates job_id is present)
    job_id, payload, error_desc = parse_error_message(msg)

    # Extract route information
    route = msg.get("route", {})
    route_steps = route.get("steps", [])
    current_index = route.get("current")

    logger.info(f"Processing error for job {job_id}: {error_desc[:100]}")

    # Persist error to S3 (if enabled)
    s3_info = persist_to_s3(
        job_id=job_id,
        data=payload,
        status="failed",
        s3_prefix=ASYA_S3_ERRORS_PREFIX,
        route_steps=route_steps,
        current_index=current_index,
        error=error_desc,
    )

    logger.warning(f"Job {job_id} failed permanently: {error_desc[:100]}")

    # Report final failure to gateway (if enabled)
    report_to_gateway(
        job_id=job_id,
        status="failed",
        error=error_desc,
        progress=None,
        s3_info=s3_info,
    )

    # Return empty dict to signal terminal processing
    # Sidecar should detect this and send to DLQ
    return {}
