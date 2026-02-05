"""
While loop with continue.

Tests skipping loop iterations.
"""


def while_with_continue_flow(p: dict) -> dict:
    p = handler_init(p)
    p["i"] = 0
    while p["i"] < p["max_iterations"]:
        p["i"] += 1
        if p["skip_iteration"]:
            continue
        p = handler_process(p)
    p = handler_finalize(p)
    return p


def handler_init(p: dict) -> dict:
    """Initialize handler."""
    return p


def handler_process(p: dict) -> dict:
    """Process handler."""
    return p


def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
