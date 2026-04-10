"""
While loop with break.

Tests early loop exit.
"""

from _asya_utils import actor, flow


@flow
def while_with_break_flow(p: dict) -> dict:
    p = handler_init(p)
    p["i"] = 0
    while p["i"] < p["max_iterations"]:
        p["i"] += 1
        p = handler_process(p)
        if p["stop_condition"]:
            break
    p = handler_finalize(p)
    return p


@actor
def handler_init(p: dict) -> dict:
    """Initialize handler."""
    return p


@actor
def handler_process(p: dict) -> dict:
    """Process handler."""
    return p


@actor
def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
