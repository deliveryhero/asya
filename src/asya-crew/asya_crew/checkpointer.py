"""
Generic checkpointer for Asya framework.

Persists complete messages (metadata + payload) as JSON files via the state proxy.
Storage backend is pluggable (S3/GCS/PostgreSQL/etc.) through the state proxy connector
configured in the AsyncActor CRD.

Environment Variables:
- ASYA_MSG_ROOT: Path to virtual filesystem for message metadata (default: /proc/asya/msg)
- ASYA_PERSISTENCE_MOUNT: State proxy mount path for checkpoint storage

VFS Paths Read:
- /proc/asya/msg/id — read-only: message UUID
- /proc/asya/msg/parent_id — read-only: parent message UUID (for fanout)
- /proc/asya/msg/route/prev — read-only: newline-separated list of processed actors
- /proc/asya/msg/route/curr — read-only: current actor name
- /proc/asya/msg/status/phase — read-only: terminal phase (succeeded/failed)

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
- Reads message metadata from VFS
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

ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")
ASYA_PERSISTENCE_MOUNT = os.getenv("ASYA_PERSISTENCE_MOUNT", "")


def _read_msg_meta(path: str, default: str = "") -> str:
    """Read message metadata field, returning default if not found."""
    try:
        with open(f"{ASYA_MSG_ROOT}/{path}") as f:
            return f.read().strip()
    except FileNotFoundError:
        return default


def handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Checkpoint handler for message persistence via state proxy.

    Reads message metadata from the VFS and persists the complete message
    (metadata + payload) as a JSON file to the configured state proxy mount.

    Args:
        payload: Message payload dict

    Returns:
        Empty dict (message passes through unchanged)

    Raises:
        ValueError: If payload is not a dict
    """
    if not isinstance(payload, dict):
        raise ValueError(f"Payload must be a dict, got {type(payload).__name__}")

    message_id = _read_msg_meta("id", "unknown")

    if not ASYA_PERSISTENCE_MOUNT:
        logger.debug(f"Checkpoint skipped for message {message_id} (ASYA_PERSISTENCE_MOUNT not set)")
        return {}

    phase = _read_msg_meta("status/phase")
    parent_id = _read_msg_meta("parent_id")
    prev_raw = _read_msg_meta("route/prev")
    prev_actors = [a for a in prev_raw.splitlines() if a] if prev_raw else []
    curr = _read_msg_meta("route/curr")

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

    return {}
