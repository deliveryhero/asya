"""
Asya sump actor handler.

The sump actor is the second layer of the two-layer termination architecture.
It is the final terminal actor that receives messages after all hooks have been processed.
It emits metrics, logs errors, and acknowledges messages.

Architecture:
    x-sink [role=sink]
        |-- Routes to hooks: [checkpoint-s3, ...]
             |
             v
        x-sump [role=sump, terminal]
             |-- Emits metrics, logs errors
             |-- ACK. Done.

Environment Variables:
- ASYA_MSG_ROOT: Path to virtual filesystem for message metadata (default: /proc/asya/msg)
- ASYA_S3_BUCKET: S3/MinIO bucket for persistence (optional, enables inline S3 persistence)

VFS Paths:
- /proc/asya/msg/id — read-only: message UUID
- /proc/asya/msg/status/{key} — read-only: status fields (e.g., phase, attempt)

Handler Behavior:
- On failed: logs complete message summary JSON at ERROR level
- On succeeded: debug-level log only
- Returns None (terminal, no further routing)
"""

import json
import logging
import os
from typing import Any


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")
ASYA_S3_BUCKET = os.getenv("ASYA_S3_BUCKET", "")


def sump_handler(payload: dict[str, Any]) -> None:
    """Sump handler. Terminal actor, logs and acknowledges."""
    with open(f"{ASYA_MSG_ROOT}/id") as f:
        message_id = f.read()

    try:
        with open(f"{ASYA_MSG_ROOT}/status/phase") as f:
            phase = f.read()
    except FileNotFoundError:
        phase = "unknown"

    if phase == "failed":
        msg_info = {"id": message_id, "phase": phase, "payload": payload}
        logger.error(f"Terminal failure for message {message_id}: {json.dumps(msg_info, indent=2, default=str)}")
    elif phase == "succeeded":
        logger.debug(f"Terminal success for message {message_id}")
    else:
        logger.info(f"Terminal non-final phase '{phase}' for message {message_id}")

    if ASYA_S3_BUCKET:
        try:
            from asya_crew.message_persistence.s3 import checkpoint_handler

            checkpoint_handler(payload)
        except Exception as e:
            logger.error(f"S3 persistence failed for message {message_id}: {e}")

    return None
