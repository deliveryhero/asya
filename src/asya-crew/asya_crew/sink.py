"""
Asya sink actor handler.

The sink actor is the first layer of the two-layer termination architecture.
It receives messages that have completed their route (either success or failure),
reports final status to the gateway, and optionally routes to configurable hooks.

Architecture:
    Pipeline (a -> b -> c)
        | route exhausted
        v
    x-sink [role=sink]
        |-- Reports final status to gateway
        |-- Routes to hooks: [checkpoint-s3, notify-slack, ...]
             |
             v
        x-sump [role=sump, terminal]

IMPORTANT: Sink handlers MUST run in envelope mode (ASYA_HANDLER_MODE=envelope)
and with validation disabled (ASYA_ENABLE_VALIDATION=false).
This module will raise RuntimeError at import time if these conditions are not met.

Environment Variables:
- ASYA_HANDLER_MODE: Handler mode (MUST be "envelope")
- ASYA_ENABLE_VALIDATION: Validation flag (MUST be "false")
- ASYA_SINK_HOOKS: Comma-separated list of hook actor names (optional)
                   Example: "checkpoint-s3,notify-slack"
- ASYA_S3_BUCKET: S3/MinIO bucket for persistence (optional, enables inline S3 persistence)

Message Structure:
    {
        "id": "<message-id>",
        "route": {"actors": [...], "current": N},
        "status": {
            "phase": "succeeded" | "failed",
            "actor": "<actor-name>",
            ...
        },
        "payload": <arbitrary JSON>
    }

Handler Behavior:
- Validates status.phase is "succeeded" or "failed"
- If ASYA_SINK_HOOKS is set: routes message to hooks by setting route.actors
- If no hooks: returns empty dict (message passes to sump directly)
- The sidecar automatically routes to the configured sink actor (x-sump)
"""

import logging
import os
from typing import Any


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ASYA_HANDLER_MODE = (os.getenv("ASYA_HANDLER_MODE") or "payload").lower()
ASYA_ENABLE_VALIDATION = os.getenv("ASYA_ENABLE_VALIDATION", "true").lower() == "true"
ASYA_SINK_HOOKS = os.getenv("ASYA_SINK_HOOKS", "")
ASYA_S3_BUCKET = os.getenv("ASYA_S3_BUCKET", "")

if ASYA_HANDLER_MODE != "envelope":
    raise RuntimeError(
        f"Sink handler must run in envelope mode. Current mode: '{ASYA_HANDLER_MODE}'. Set ASYA_HANDLER_MODE=envelope"
    )

if ASYA_ENABLE_VALIDATION:
    raise RuntimeError(
        "Sink handler must run with validation disabled. Current setting: ASYA_ENABLE_VALIDATION=true. "
        "Set ASYA_ENABLE_VALIDATION=false"
    )


def sink_handler(message: dict[str, Any]) -> dict[str, Any]:
    """
    Sink handler for message termination.

    Processes messages that have completed their route (success or failure).
    Reports final status to gateway and optionally routes to hooks.

    Args:
        message: Complete message with id, route, status, payload

    Returns:
        Message with updated route if hooks configured, empty dict otherwise

    Raises:
        ValueError: If message is missing required fields or has invalid status.phase
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

    phase = status.get("phase")
    if phase not in ("succeeded", "failed"):
        raise ValueError(f"Invalid status.phase: {phase!r}. Must be 'succeeded' or 'failed'")

    message_id = message["id"]
    logger.info(f"Processing sink for message {message_id}, phase={phase}")

    if ASYA_S3_BUCKET:
        try:
            from asya_crew.message_persistence.s3 import checkpoint_handler

            checkpoint_handler(message)
        except Exception as e:
            logger.error(f"S3 persistence failed for message {message_id}: {e}")

    if ASYA_SINK_HOOKS:
        hooks = [h.strip() for h in ASYA_SINK_HOOKS.split(",") if h.strip()]
        if hooks:
            logger.info(f"Routing message {message_id} to hooks: {hooks}")
            message["route"] = {"actors": hooks, "current": 0}
            return message

    logger.info(f"No hooks configured, message {message_id} passes through to sump")
    return {}
