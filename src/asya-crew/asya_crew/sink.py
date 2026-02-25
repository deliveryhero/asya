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

Environment Variables:
- ASYA_MSG_ROOT: Path to virtual filesystem for message metadata (default: /proc/asya/msg)
- ASYA_SINK_HOOKS: Comma-separated list of hook actor names (optional)
                   Example: "checkpoint-s3,notify-slack"
- ASYA_SINK_FANOUT_HOOKS: When "true", run hooks even for fire-and-forget fan-out children
                           (messages with parent_id set but no x-asya-fan-in header).
                           Default: "false" — fan-out children skip hooks silently.
- ASYA_PERSISTENCE_MOUNT: State proxy mount path for inline checkpoint persistence (optional)

VFS Paths:
- /proc/asya/msg/id — read-only: message UUID
- /proc/asya/msg/parent_id — read-only: parent UUID (empty if unset)
- /proc/asya/msg/route/next — read-write: newline-separated actor list
- /proc/asya/msg/headers/{key} — read-write: individual headers
- /proc/asya/msg/status/{key} — read-only: status fields (e.g., phase, attempt)

Handler Behavior:
- Accepts any status.phase value (no strict validation)
- Fire-and-forget fan-out children (parent_id set, no x-asya-fan-in header): skip hooks by default
  unless ASYA_SINK_FANOUT_HOOKS=true
- Fan-in partials (x-asya-fan-in header): always run hooks (aggregation handled by caller)
- If ASYA_SINK_HOOKS is set and hooks should run: routes message to hooks by writing to route/next
- If no hooks (or hooks skipped): returns payload (message passes to sump directly)
- The sidecar automatically routes to the configured sink actor (x-sump)
"""

import logging
import os
from typing import Any


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")
ASYA_SINK_HOOKS = os.getenv("ASYA_SINK_HOOKS", "")
ASYA_SINK_FANOUT_HOOKS = os.getenv("ASYA_SINK_FANOUT_HOOKS", "false").lower() == "true"
ASYA_PERSISTENCE_MOUNT = os.getenv("ASYA_PERSISTENCE_MOUNT", "")


def sink_handler(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Sink handler. Receives payload, accesses metadata via /proc/asya/msg/."""
    with open(f"{ASYA_MSG_ROOT}/id") as f:
        message_id = f.read()

    try:
        with open(f"{ASYA_MSG_ROOT}/status/phase") as f:
            phase = f.read()
    except FileNotFoundError:
        phase = "unknown"

    try:
        with open(f"{ASYA_MSG_ROOT}/headers/x-asya-fan-in") as f:
            has_fan_in = bool(f.read())
    except FileNotFoundError:
        has_fan_in = False

    with open(f"{ASYA_MSG_ROOT}/parent_id") as f:
        has_parent_id = bool(f.read())

    logger.info(
        f"Processing sink for message {message_id}, phase={phase}, fan_in={has_fan_in}, parent_id={has_parent_id}"
    )

    if ASYA_PERSISTENCE_MOUNT:
        try:
            from asya_crew.checkpointer import handler

            handler(payload)
        except Exception as e:
            logger.error(f"Checkpoint failed for message {message_id}: {e}")

    if has_parent_id and not has_fan_in and not ASYA_SINK_FANOUT_HOOKS:
        logger.info(f"Fan-out child (parent_id set), skipping hooks for message {message_id}")
        return payload

    if ASYA_SINK_HOOKS:
        hooks = [h.strip() for h in ASYA_SINK_HOOKS.split(",") if h.strip()]
        if hooks:
            logger.info(f"Routing message {message_id} to hooks: {hooks}")
            with open(f"{ASYA_MSG_ROOT}/route/next", "w") as f:
                f.write("\n".join(hooks))
            return payload

    logger.info(f"No hooks configured, message {message_id} passes through to sump")
    return payload
