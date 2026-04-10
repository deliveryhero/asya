"""
While loop with mutations.

Tests mutations inside loop body.
"""

from _asya_utils import actor, flow


@flow
def while_mutations_in_loop_flow(p: dict) -> dict:
    p = handler_init(p)
    p["i"] = 0
    p["sum"] = 0
    while p["i"] < p["max_iterations"]:
        p["i"] += 1
        p["sum"] += p["i"]
        p["step"] = p["i"]
        p = handler_process(p)
        p["processed"] = True
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
