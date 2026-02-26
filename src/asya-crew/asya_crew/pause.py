"""
x-pause crew actor for Asya framework.

Pauses message processing by persisting the message state and signaling the gateway
via the x-asya-pause header. The message is stored for later resumption by x-resume.

Environment Variables:
- ASYA_MSG_ROOT: Path to virtual filesystem for message metadata (default: /proc/asya/msg)
- ASYA_PERSISTENCE_MOUNT: State proxy mount path for paused message storage
- ASYA_PAUSE_METADATA: Optional JSON string with pause metadata (prompt + fields schema)

VFS Paths Read:
- /proc/asya/msg/id — read-only: message UUID
- /proc/asya/msg/parent_id — read-only: parent message UUID (for fanout)
- /proc/asya/msg/route/prev — read-only: newline-separated list of processed actors
- /proc/asya/msg/route/curr — read-only: current actor name
- /proc/asya/msg/route/next — read-write: newline-separated list of pending actors
- /proc/asya/msg/headers/* — read: all headers, write: x-asya-pause

VFS Paths Written:
- /proc/asya/msg/route/next — prepend x-resume if missing
- /proc/asya/msg/headers/x-asya-pause — pause signal with metadata JSON

File Path Structure:
    {mount}/paused/{msg_id}.json

Handler Behavior:
- Reads message metadata from VFS
- Ensures x-resume is first in route.next (prepends if missing)
- Persists full message (metadata + headers + payload + pause metadata) to state proxy mount
- Sets x-asya-pause header with pause metadata
- Returns payload so runtime builds a frame with VFS headers for sidecar detection
- Gracefully skips persistence if ASYA_PERSISTENCE_MOUNT not set

IMPORTANT — Return Value Contract:
    This handler MUST return the payload dict, not None. The runtime only includes
    VFS-written headers (like x-asya-pause) in response frames built by _build_frame().
    When a handler returns None, the runtime responds with HTTP 204 (no body), and the
    sidecar receives zero frames. With no frames to inspect, the sidecar treats the
    message as end-of-route and sends it to x-sink — silently skipping the pause signal.
    Returning payload ensures the runtime builds a frame carrying VFS headers through the
    Unix socket to the sidecar, where x-asya-pause is detected and forwarding is halted.
"""

import contextlib
import json
import logging
import os
from typing import Any


logger = logging.getLogger(__name__)

ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")
ASYA_PERSISTENCE_MOUNT = os.getenv("ASYA_PERSISTENCE_MOUNT", "")
ASYA_PAUSE_METADATA = os.getenv("ASYA_PAUSE_METADATA", "")

# Transient headers excluded from persistence
TRANSIENT_HEADERS = {
    "x-asya-fan-in",
    "x-asya-route-override",
    "x-asya-route-resolved",
    "x-asya-parent-id",
}


def _read_msg_meta(path: str, default: str = "") -> str:
    """Read message metadata field, returning default if not found."""
    try:
        with open(f"{ASYA_MSG_ROOT}/{path}") as f:
            return f.read().strip()
    except FileNotFoundError:
        return default


def _write_msg_meta(path: str, content: str) -> None:
    """Write message metadata field."""
    full_path = f"{ASYA_MSG_ROOT}/{path}"
    with open(full_path, "w") as f:
        f.write(content)


def _read_headers() -> dict[str, Any]:
    """Read all non-transient headers from VFS."""
    headers: dict[str, Any] = {}
    headers_dir = f"{ASYA_MSG_ROOT}/headers"

    if not os.path.isdir(headers_dir):
        return headers

    for filename in os.listdir(headers_dir):
        if filename in TRANSIENT_HEADERS:
            continue

        filepath = os.path.join(headers_dir, filename)
        if not os.path.isfile(filepath):
            continue

        try:
            with open(filepath) as f:
                content = f.read().strip()
            # Try JSON parse
            try:
                headers[filename] = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                # Store as raw string if not valid JSON
                headers[filename] = content
        except Exception as e:
            logger.warning(f"Failed to read header {filename}: {e}")

    return headers


def pause_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    x-pause crew actor handler.

    1. Verify x-resume is next in route (safety check)
       Read /proc/asya/msg/route/next, if first actor is not "x-resume", prepend it.

    2. Persist full message to storage (reuse checkpointer pattern)
       Use ASYA_PERSISTENCE_MOUNT. S3 key prefix: "paused/" (not "checkpoint/")
       Include _pause_metadata in the persisted document.
       The persisted document should contain:
       {
         "id": msg_id,
         "route": {"prev": [...], "curr": curr, "next": [remaining_actors]},
         "headers": {non-transient headers},
         "payload": payload,
         "_pause_metadata": {parsed from env or header}
       }
       The file should be stored at: {mount}/paused/{msg_id}.json

    3. Signal pause via x-asya-pause header
       Write JSON to /proc/asya/msg/headers/x-asya-pause
       The JSON should contain the pause metadata (prompt, fields).

    4. Return payload so the runtime builds a response frame with VFS headers.
       The sidecar detects x-asya-pause and stops forwarding.

    Args:
        payload: Message payload dict

    Returns:
        The original payload (sidecar uses x-asya-pause header to halt forwarding)

    Raises:
        ValueError: If payload is not a dict
    """
    if not isinstance(payload, dict):
        raise ValueError(f"Payload must be a dict, got {type(payload).__name__}")

    message_id = _read_msg_meta("id", "unknown")

    # Parse pause metadata from env var
    pause_metadata: dict[str, Any] = {"prompt": "Task paused", "fields": []}
    if ASYA_PAUSE_METADATA:
        try:
            pause_metadata = json.loads(ASYA_PAUSE_METADATA)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse ASYA_PAUSE_METADATA, using default: {e}")

    # Read current route.next
    next_raw = _read_msg_meta("route/next")
    next_actors = [a for a in next_raw.splitlines() if a] if next_raw else []

    # Prepend x-resume if not already first
    if not next_actors or next_actors[0] != "x-resume":
        next_actors.insert(0, "x-resume")
        _write_msg_meta("route/next", "\n".join(next_actors))
        logger.debug(f"Prepended x-resume to route.next for message {message_id}")

    # Read other message metadata
    parent_id = _read_msg_meta("parent_id")
    prev_raw = _read_msg_meta("route/prev")
    prev_actors = [a for a in prev_raw.splitlines() if a] if prev_raw else []
    curr = _read_msg_meta("route/curr")

    # Read headers (excluding transient)
    headers = _read_headers()

    # Persist full message if mount is configured
    if ASYA_PERSISTENCE_MOUNT:
        key = f"paused/{message_id}.json"
        file_path = f"{ASYA_PERSISTENCE_MOUNT}/{key}"

        message: dict[str, Any] = {
            "id": message_id,
            "route": {
                "prev": prev_actors,
                "curr": curr,
                "next": next_actors,
            },
            "headers": headers,
            "payload": payload,
            "_pause_metadata": pause_metadata,
        }
        if parent_id:
            message["parent_id"] = parent_id

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
            logger.info(f"Paused message {message_id} to {file_path}")
        except Exception as e:
            logger.error(f"Failed to persist paused message {message_id}: {e}", exc_info=True)
            raise
    else:
        logger.debug(f"Pause persistence skipped for message {message_id} (ASYA_PERSISTENCE_MOUNT not set)")

    # Write x-asya-pause header
    try:
        pause_header_json = json.dumps(pause_metadata)
        _write_msg_meta("headers/x-asya-pause", pause_header_json)
        logger.info(f"Set x-asya-pause header for message {message_id}")
    except Exception as e:
        logger.error(f"Failed to set x-asya-pause header for message {message_id}: {e}", exc_info=True)
        raise

    # Return payload so the runtime builds a response frame containing VFS headers
    # (including x-asya-pause). The sidecar detects the header and stops forwarding.
    return payload
