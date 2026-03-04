"""
Generic checkpointer for Asya framework.

Persists complete messages (metadata + payload) as JSON files via the state proxy.
Storage backend is pluggable (S3/GCS/PostgreSQL/etc.) through the state proxy connector
configured in the AsyncActor CRD.

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
- Accepts message metadata as function arguments (called from sink/sump generators)
- Persists full message (metadata + payload) as JSON to state proxy mount
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
    phase: str = "",
    parent_id: str = "",
    prev_actors: list[str] | None = None,
    curr: str = "",
) -> None:
    """
    Checkpoint handler for message persistence via state proxy.

    Persists the complete message (metadata + payload) as a JSON file
    to the configured state proxy mount.

    Args:
        payload: Message payload dict
        message_id: Envelope ID
        phase: Terminal phase (succeeded/failed)
        parent_id: Parent envelope ID (for fanout tracking)
        prev_actors: List of previously processed actors
        curr: Current actor name

    Raises:
        ValueError: If payload is not a dict
    """
    if not isinstance(payload, dict):
        raise ValueError(f"Payload must be a dict, got {type(payload).__name__}")

    if not ASYA_PERSISTENCE_MOUNT:
        logger.debug(f"Checkpoint skipped for message {message_id} (ASYA_PERSISTENCE_MOUNT not set)")
        return

    if prev_actors is None:
        prev_actors = []

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
            "curr": curr,
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
