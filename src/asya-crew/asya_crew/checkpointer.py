"""
Generic checkpointer for Asya framework.

Persists complete messages (metadata + payload) as JSON files via the state proxy.
Storage backend is pluggable (S3/GCS/PostgreSQL/etc.) through the state proxy connector
configured in the AsyncActor CRD.

Called from the sink handler, which passes message metadata obtained via ABI protocol.

Environment Variables:
- ASYA_PERSISTENCE_MOUNT: State proxy mount path for checkpoint storage

File Path Structure:
    {mount}/{prefix}/{timestamp}/{actor}/{id}.json

Prefixes:
- succeeded/ - Messages with status.phase == "succeeded"
- failed/ - Messages with status.phase == "failed"
- checkpoint/ - Messages without status.phase (mid-pipeline)

Examples:
    /state/checkpoints/succeeded/2026-02-12T10:30:00.123456Z/text-processor/msg-123.json
    /state/checkpoints/failed/2026-02-12T10:30:00.123456Z/image-analyzer/msg-456.json

Handler Behavior:
- Receives message metadata as keyword arguments from caller (sink handler)
- Persists full message (metadata + payload) as JSON to state proxy mount
- Returns empty dict (message passes through unchanged)
- Gracefully skips if ASYA_PERSISTENCE_MOUNT not set
"""

import contextlib
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any


logger = logging.getLogger(__name__)

ASYA_PERSISTENCE_MOUNT = os.getenv("ASYA_PERSISTENCE_MOUNT", "")


def handler(
    payload: dict[str, Any],
    *,
    message_id: str = "unknown",
    parent_id: str = "",
    phase: str = "",
    route_prev: list[str] | None = None,
    route_curr: str = "",
) -> dict[str, Any]:
    """
    Checkpoint handler for message persistence via state proxy.

    Receives message metadata as keyword arguments from the sink handler,
    and persists the complete message (metadata + payload) as a JSON file
    to the configured state proxy mount.

    Args:
        payload: Message payload dict
        message_id: Message UUID
        parent_id: Parent message UUID (for fanout)
        phase: Terminal phase (succeeded/failed)
        route_prev: List of processed actors
        route_curr: Current actor name

    Returns:
        Empty dict (message passes through unchanged)

    Raises:
        ValueError: If payload is not a dict
    """
    if not isinstance(payload, dict):
        raise ValueError(f"Payload must be a dict, got {type(payload).__name__}")

    if not ASYA_PERSISTENCE_MOUNT:
        logger.debug(f"Checkpoint skipped for message {message_id} (ASYA_PERSISTENCE_MOUNT not set)")
        return {}

    prev_actors = route_prev if route_prev is not None else []

    if phase == "succeeded":
        prefix = "succeeded"
    elif phase == "failed":
        prefix = "failed"
    else:
        prefix = "checkpoint"

    actor = prev_actors[-1] if prev_actors else "unknown"

    now = datetime.now(tz=UTC)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    key = f"{prefix}/{timestamp}/{actor}/{message_id}.json"
    file_path = f"{ASYA_PERSISTENCE_MOUNT}/{key}"

    message: dict[str, Any] = {
        "id": message_id,
        "route": {
            "prev": prev_actors,
            "curr": route_curr,
        },
        "payload": payload,
    }
    if parent_id:
        message["parent_id"] = parent_id
    if phase:
        message["status"] = {"phase": phase}

    try:
        body = json.dumps(message, indent=2, default=str)
    except (TypeError, ValueError) as e:
        logger.error(f"Failed to serialize message {message_id}: {e}")
        raise

    try:
        with contextlib.suppress(OSError):
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as f:
            f.write(body)
        logger.info(f"Checkpointed message {message_id} to {file_path}")
    except Exception as e:
        logger.error(f"Failed to checkpoint message {message_id}: {e}", exc_info=True)

    return {}
