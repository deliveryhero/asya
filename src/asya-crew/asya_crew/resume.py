"""
x-resume crew actor handler.

Restores paused messages from state proxy storage and merges user input
to continue execution.

Environment Variables:
- ASYA_MSG_ROOT: Path to virtual filesystem for message metadata (default: /proc/asya/msg)
- ASYA_PERSISTENCE_MOUNT: State proxy mount path for persisted messages (required)
- ASYA_RESUME_MERGE_MODE: "shallow" (default) or "deep" - merge strategy when no field mappings

VFS Paths Read:
- /proc/asya/msg/headers/x-asya-resume-task - Task ID to locate persisted message
- /proc/asya/msg/headers/x-asya-resume-timeout - Optional remaining timeout in seconds

VFS Paths Written:
- /proc/asya/msg/route/next - Restored route from persisted message
- /proc/asya/msg/headers/x-asya-deadline-at - New deadline timestamp (if timeout provided)

VFS Paths Deleted:
- /proc/asya/msg/headers/x-asya-resume-task - Cleanup after reading
- /proc/asya/msg/headers/x-asya-resume-timeout - Cleanup after reading

Handler Behavior:
1. Read task ID from x-asya-resume-task header
2. Load persisted message from {ASYA_PERSISTENCE_MOUNT}/paused/{task_id}.json
3. Merge user input into restored payload using field mappings from pause metadata
4. Restore route by writing route.next to VFS
5. Handle timeout by computing new deadline from x-asya-resume-timeout header
6. Clean up persisted file and header files
7. Return merged payload
"""

import contextlib
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any


logger = logging.getLogger(__name__)

ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")
ASYA_PERSISTENCE_MOUNT = os.getenv("ASYA_PERSISTENCE_MOUNT", "")
ASYA_RESUME_MERGE_MODE = os.getenv("ASYA_RESUME_MERGE_MODE", "shallow")


def _read_msg_meta(path: str, default: str = "") -> str:
    """Read message metadata field, returning default if not found."""
    try:
        with open(f"{ASYA_MSG_ROOT}/{path}") as f:
            return f.read().strip()
    except FileNotFoundError:
        return default


def _set_at_path(obj: dict, path: str, value: Any) -> None:
    """Set a value at a /-separated path in a nested dict, creating intermediate dicts."""
    parts = [p for p in path.split("/") if p]
    current = obj
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    if parts:
        current[parts[-1]] = value


def resume_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Resume handler for restoring paused messages and merging user input.

    Loads persisted message from state proxy storage, merges user input
    according to field mappings in pause metadata, restores the route,
    and handles timeout renewal.

    Args:
        payload: User input dict to merge into restored payload

    Returns:
        Merged payload dict combining restored payload with user input

    Raises:
        ValueError: If ASYA_PERSISTENCE_MOUNT not set or payload not a dict
        FileNotFoundError: If persisted message file not found
    """
    if not isinstance(payload, dict):
        raise ValueError(f"Payload must be a dict, got {type(payload).__name__}")

    if not ASYA_PERSISTENCE_MOUNT:
        raise ValueError("ASYA_PERSISTENCE_MOUNT not set")

    task_id = _read_msg_meta("headers/x-asya-resume-task")
    if not task_id:
        raise ValueError("x-asya-resume-task header not found")

    persisted_path = os.path.join(ASYA_PERSISTENCE_MOUNT, "paused", f"{task_id}.json")

    with open(persisted_path) as f:
        persisted_msg = json.load(f)

    pause_metadata = persisted_msg.get("_pause_metadata", {})
    fields = pause_metadata.get("fields", [])
    restored_payload = persisted_msg["payload"]

    if fields:
        for field in fields:
            field_name = field["name"]
            if field_name in payload:
                payload_key = field.get("payload_key", f"/{field_name}")
                _set_at_path(restored_payload, payload_key, payload[field_name])
    else:
        if ASYA_RESUME_MERGE_MODE == "deep":
            _deep_merge(restored_payload, payload)
        else:
            restored_payload.update(payload)

    route_next = persisted_msg["route"]["next"]
    next_path = os.path.join(ASYA_MSG_ROOT, "route", "next")
    with open(next_path, "w") as f:
        f.write("\n".join(route_next))

    timeout_header = _read_msg_meta("headers/x-asya-resume-timeout")
    if timeout_header:
        try:
            remaining_seconds = float(timeout_header)
            deadline_at = datetime.now(tz=UTC) + timedelta(seconds=remaining_seconds)
            deadline_str = deadline_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            deadline_path = os.path.join(ASYA_MSG_ROOT, "headers", "x-asya-deadline-at")
            os.makedirs(os.path.dirname(deadline_path), exist_ok=True)
            with open(deadline_path, "w") as f:
                f.write(deadline_str)

            logger.debug(f"Set deadline to {deadline_str} ({remaining_seconds}s from now)")
        except ValueError as e:
            logger.warning(f"Invalid x-asya-resume-timeout value: {timeout_header} ({e})")

    with contextlib.suppress(FileNotFoundError, OSError):
        os.remove(persisted_path)

    with contextlib.suppress(FileNotFoundError, OSError):
        os.remove(os.path.join(ASYA_MSG_ROOT, "headers", "x-asya-resume-task"))

    with contextlib.suppress(FileNotFoundError, OSError):
        os.remove(os.path.join(ASYA_MSG_ROOT, "headers", "x-asya-resume-timeout"))

    logger.info(f"Resumed task {task_id} with {len(route_next)} actors remaining")

    return restored_payload


def _deep_merge(target: dict, source: dict) -> None:
    """Deep merge source dict into target dict."""
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
