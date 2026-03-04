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
- ASYA_PERSISTENCE_MOUNT: State proxy mount path for inline checkpoint persistence (optional)

ABI Paths Used:
- GET .id — read-only: message UUID
- GET .status.phase — read-only: terminal phase
- GET .parent_id — read-only: parent UUID (for checkpointer)
- GET .route.prev — read-only: list of processed actors (for checkpointer)
- GET .route.curr — read-only: current actor name (for checkpointer)

Handler Behavior:
- Generator handler using ABI yield protocol for metadata access
- On failed: logs complete message summary JSON at ERROR level
- On succeeded: debug-level log only
- Does not emit any payload (terminal, no further routing)
"""

import json
import logging
import os
from collections.abc import Generator
from typing import Any


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ASYA_PERSISTENCE_MOUNT = os.getenv("ASYA_PERSISTENCE_MOUNT", "")


def sump_handler(payload: dict[str, Any]) -> Generator:
    """Sump handler. Terminal actor, logs and acknowledges."""
    message_id: str = (yield "GET", ".id") or ""

    phase: str = (yield "GET", ".status.phase") or ""

    if phase == "failed":
        msg_info = {"id": message_id, "phase": phase, "payload": payload}
        logger.error(f"Terminal failure for message {message_id}: {json.dumps(msg_info, indent=2, default=str)}")
    elif phase == "succeeded":
        logger.debug(f"Terminal success for message {message_id}")
    else:
        phase_label = phase if phase else "unknown"
        logger.info(f"Terminal non-final phase '{phase_label}' for message {message_id}")

    if ASYA_PERSISTENCE_MOUNT:
        try:
            from asya_crew.checkpointer import handler

            parent_id: str = (yield "GET", ".parent_id") or ""
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
