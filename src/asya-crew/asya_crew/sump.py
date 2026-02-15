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

IMPORTANT: Sump handlers MUST run in envelope mode (ASYA_HANDLER_MODE=envelope)
and with validation disabled (ASYA_ENABLE_VALIDATION=false).
This module will raise RuntimeError at import time if these conditions are not met.

Environment Variables:
- ASYA_HANDLER_MODE: Handler mode (MUST be "envelope")
- ASYA_ENABLE_VALIDATION: Validation flag (MUST be "false")
- ASYA_S3_BUCKET: S3/MinIO bucket for persistence (optional, enables inline S3 persistence)

Message Structure:
    {
        "id": "<message-id>",
        "status": {
            "phase": "succeeded" | "failed",
            ...
        },
        "payload": <arbitrary JSON>,
        "error": "<error-message>" (optional, for failed messages)
    }

Handler Behavior:
- On failed: logs complete message JSON at ERROR level
- On succeeded: debug-level log only
- Returns None (terminal, no further routing)
"""

import json
import logging
import os
from typing import Any


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ASYA_HANDLER_MODE = (os.getenv("ASYA_HANDLER_MODE") or "payload").lower()
ASYA_ENABLE_VALIDATION = os.getenv("ASYA_ENABLE_VALIDATION", "true").lower() == "true"
ASYA_S3_BUCKET = os.getenv("ASYA_S3_BUCKET", "")

if ASYA_HANDLER_MODE != "envelope":
    raise RuntimeError(
        f"Sump handler must run in envelope mode. Current mode: '{ASYA_HANDLER_MODE}'. Set ASYA_HANDLER_MODE=envelope"
    )

if ASYA_ENABLE_VALIDATION:
    raise RuntimeError(
        "Sump handler must run with validation disabled. Current setting: ASYA_ENABLE_VALIDATION=true. "
        "Set ASYA_ENABLE_VALIDATION=false"
    )


def sump_handler(message: dict[str, Any]) -> None:
    """
    Sump handler for terminal message processing.

    Final terminal actor that logs errors and emits metrics.

    Args:
        message: Complete message with id, status, payload

    Returns:
        None (terminal, no further routing)

    Raises:
        ValueError: If message is missing required fields
    """
    if not isinstance(message, dict):
        raise ValueError(f"Message must be a dict, got {type(message).__name__}")

    if "id" not in message:
        raise ValueError("Message missing required field: id")

    if "status" not in message:
        raise ValueError("Message missing required field: status")

    status = message.get("status")
    if not isinstance(status, dict):
        raise ValueError(f"Message status must be a dict, got {type(status).__name__}")

    message_id = message["id"]
    phase = status.get("phase", "unknown")

    if phase == "failed":
        logger.error(f"Terminal failure for message {message_id}: {json.dumps(message, indent=2, default=str)}")
    else:
        logger.debug(f"Terminal success for message {message_id}")

    if ASYA_S3_BUCKET:
        try:
            from asya_crew.message_persistence.s3 import checkpoint_handler

            checkpoint_handler(message)
        except Exception as e:
            logger.error(f"S3 persistence failed for message {message_id}: {e}")

    return None
