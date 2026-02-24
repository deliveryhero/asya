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
- ASYA_SINK_FANOUT_HOOKS: When "true", run hooks even for fire-and-forget fan-out children
                           (messages with parent_id set but no x-asya-fan-in header).
                           Default: "false" — fan-out children skip hooks silently.
- ASYA_S3_BUCKET: S3/MinIO bucket for persistence (optional, enables inline S3 persistence)

Message Structure:
    {
        "id": "<message-id>",
        "parent_id": "<original-message-id>",  // optional, for fanout children
        "route": {"prev": [...], "curr": "<actor>", "next": [...]},
        "headers": {"x-asya-fan-in": "aggregator", ...},  // optional
        "status": {
            "phase": "<any phase>",  // any value accepted
            "actor": "<actor-name>",
            ...
        },
        "payload": <arbitrary JSON>
    }

Handler Behavior:
- Accepts any status.phase value (no strict validation)
- Fire-and-forget fan-out children (parent_id set, no x-asya-fan-in header): skip hooks by default
  unless ASYA_SINK_FANOUT_HOOKS=true
- Fan-in partials (x-asya-fan-in header): always run hooks (aggregation handled by caller)
- If ASYA_SINK_HOOKS is set and hooks should run: routes message to hooks by setting route.actors
- If no hooks (or hooks skipped): returns empty dict (message passes to sump directly)
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
ASYA_SINK_FANOUT_HOOKS = os.getenv("ASYA_SINK_FANOUT_HOOKS", "false").lower() == "true"
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

    Processes messages that have completed their route (any phase).
    Optionally routes to hooks; suppresses hooks for fire-and-forget fan-out children.

    Args:
        message: Complete message with id, route, status, payload

    Returns:
        Message with updated route if hooks configured and applicable, empty dict otherwise

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

    phase = status.get("phase")
    has_fan_in = bool((message.get("headers") or {}).get("x-asya-fan-in"))
    has_parent_id = message.get("parent_id") is not None

    message_id = message["id"]
    logger.info(
        f"Processing sink for message {message_id}, phase={phase}, fan_in={has_fan_in}, parent_id={has_parent_id}"
    )

    if ASYA_S3_BUCKET:
        try:
            from asya_crew.message_persistence.s3 import checkpoint_handler

            checkpoint_handler(message)
        except Exception as e:
            logger.error(f"S3 persistence failed for message {message_id}: {e}")

    # Fire-and-forget fan-out children: skip hooks unless ASYA_SINK_FANOUT_HOOKS=true.
    # Fan-in partials (x-asya-fan-in header) always run hooks.
    if has_parent_id and not has_fan_in and not ASYA_SINK_FANOUT_HOOKS:
        logger.info(f"Fan-out child (parent_id set), skipping hooks for message {message_id}")
        return {}

    if ASYA_SINK_HOOKS:
        hooks = [h.strip() for h in ASYA_SINK_HOOKS.split(",") if h.strip()]
        if hooks:
            logger.info(f"Routing message {message_id} to hooks: {hooks}")
            message["route"] = {
                "prev": [],
                "curr": hooks[0],
                "next": hooks[1:],
            }
            return message

    logger.info(f"No hooks configured, message {message_id} passes through to sump")
    return {}
