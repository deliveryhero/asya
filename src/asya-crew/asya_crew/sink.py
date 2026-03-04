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

ABI Protocol:
- yield ("GET", ".id") -> message UUID
- yield ("GET", ".parent_id") -> parent UUID (empty if unset)
- yield ("GET", ".status") -> status dict (may contain "phase")
- yield ("GET", ".headers") -> headers dict (may contain "x-asya-fan-in")
- yield ("GET", ".route") -> route dict with prev/curr/next
- yield ("SET", ".route.next", [...]) -> set next actors for hook routing
- yield payload -> emit downstream frame

Handler Behavior:
- Accepts any status.phase value (no strict validation)
- Fan-in partials (x-asya-fan-in header): silently consumed, no checkpoint or hooks
  (these are accumulating slices that should not produce visible results)
- Fire-and-forget fan-out children (parent_id set, no x-asya-fan-in header): skip hooks by default
  unless ASYA_SINK_FANOUT_HOOKS=true
- x-asya-origin-id header: when present, used as the checkpoint filename (instead of envelope ID)
  so the merged fan-in result is stored under the original task ID
- If ASYA_SINK_HOOKS is set and hooks should run: routes message to hooks via ABI SET
- If no hooks (or hooks skipped): yields payload (message passes to sump directly)
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


def sink_handler(payload: dict[str, Any]) -> Generator[tuple | dict[str, Any], Any, None]:
    """Sink handler. Receives payload, accesses metadata via ABI yield protocol."""
    message_id: str = yield "GET", ".id"
    parent_id: str = yield "GET", ".parent_id"

    status: dict[str, Any] = yield "GET", ".status"
    phase = status.get("phase", "unknown")

    headers: dict[str, Any] = yield "GET", ".headers"
    has_fan_in = bool(headers.get("x-asya-fan-in"))
    has_parent_id = bool(parent_id)

    logger.info(
        f"Processing sink for message {message_id}, phase={phase}, fan_in={has_fan_in}, parent_id={has_parent_id}"
    )

    # Fan-in partials (accumulating slices) are silently consumed.
    # They arrive at x-sink because the sidecar routes empty responses here,
    # but they should not produce checkpoints or gateway reports.
    if has_fan_in:
        logger.info(f"Fan-in partial (x-asya-fan-in header), suppressing for message {message_id}")
        return

    # Use x-asya-origin-id header (set by the fan-in aggregator on merged results)
    # as the checkpoint filename so the result is stored under the original task ID.
    checkpoint_id = headers.get("x-asya-origin-id", "") or message_id

    if ASYA_PERSISTENCE_MOUNT:
        try:
            from asya_crew.checkpointer import handler

            route: dict[str, Any] = yield "GET", ".route"
            handler(
                payload,
                message_id=checkpoint_id,
                parent_id=parent_id,
                phase=phase,
                route_prev=route.get("prev", []),
                route_curr=route.get("curr", ""),
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
