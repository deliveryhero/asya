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
- ASYA_SINK_HOOKS: Comma-separated list of hook actor names (optional)
                   Example: "checkpoint-s3,notify-slack"
- ASYA_SINK_FANOUT_HOOKS: When "true", run hooks even for fire-and-forget fan-out children
                           (messages with parent_id set but no x-asya-fan-in header).
                           Default: "false" — fan-out children skip hooks silently.
- ASYA_PERSISTENCE_MOUNT: State proxy mount path for inline checkpoint persistence (optional)

ABI Paths Used:
- GET .id — read-only: message UUID
- GET .parent_id — read-only: parent UUID (empty if unset)
- GET .status.phase — read-only: terminal phase
- GET .headers.x-asya-fan-in — read-only: fan-in header
- GET .route.prev — read-only: list of processed actors
- GET .route.curr — read-only: current actor name
- SET .route.next — read-write: list of next actors

Handler Behavior:
- Generator handler using ABI yield protocol for metadata access
- Accepts any status.phase value (no strict validation)
- Fire-and-forget fan-out children (parent_id set, no x-asya-fan-in header): skip hooks by default
  unless ASYA_SINK_FANOUT_HOOKS=true
- Fan-in partials (x-asya-fan-in header): always run hooks (aggregation handled by caller)
- If ASYA_SINK_HOOKS is set and hooks should run: routes message to hooks by SET .route.next
- If no hooks (or hooks skipped): emits payload (message passes to sump directly)
- The sidecar automatically routes to the configured sink actor (x-sump)
"""

import logging
import os
from collections.abc import Generator
from typing import Any


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ASYA_SINK_HOOKS = os.getenv("ASYA_SINK_HOOKS", "")
ASYA_SINK_FANOUT_HOOKS = os.getenv("ASYA_SINK_FANOUT_HOOKS", "false").lower() == "true"
ASYA_PERSISTENCE_MOUNT = os.getenv("ASYA_PERSISTENCE_MOUNT", "")


def sink_handler(payload: dict[str, Any]) -> Generator:
    """Sink handler. Receives payload, accesses metadata via ABI yield protocol."""
    message_id: str = (yield "GET", ".id") or ""

    phase: str = (yield "GET", ".status.phase") or ""

    headers: dict[str, Any] = (yield "GET", ".headers") or {}
    has_fan_in = bool(headers.get("x-asya-fan-in", ""))

    parent_id: str = (yield "GET", ".parent_id") or ""
    has_parent_id = bool(parent_id)

    logger.info(
        f"Processing sink for message {message_id}, phase={phase}, fan_in={has_fan_in}, parent_id={has_parent_id}"
    )

    if ASYA_PERSISTENCE_MOUNT:
        try:
            from asya_crew.checkpointer import handler

            prev_actors: list[str] = (yield "GET", ".route.prev") or []
            curr: str = (yield "GET", ".route.curr") or ""

            handler(
                payload,
                message_id=message_id,
                phase=phase,
                parent_id=parent_id,
                prev_actors=prev_actors,
                curr=curr,
            )
        except Exception as e:
            logger.error(f"Checkpoint failed for message {message_id}: {e}")

    if has_parent_id and not has_fan_in and not ASYA_SINK_FANOUT_HOOKS:
        logger.info(f"Fan-out child (parent_id set), skipping hooks for message {message_id}")
        yield payload
        return

    if ASYA_SINK_HOOKS:
        hooks = [h.strip() for h in ASYA_SINK_HOOKS.split(",") if h.strip()]
        if hooks:
            logger.info(f"Routing message {message_id} to hooks: {hooks}")
            yield "SET", ".route.next", hooks
            yield payload
            return

    logger.info(f"No hooks configured, message {message_id} passes through to sump")
    yield payload
