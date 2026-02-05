"""
While loop with both break and continue.

Tests complex loop control flow.
"""


def while_break_continue_flow(p: dict) -> dict:
    p = handler_init(p)
    p["i"] = 0
    while p["i"] < p["max_iterations"]:
        p["i"] += 1
        p = handler_check(p)
        if p["skip"]:
            continue
        p = handler_process(p)
        if p["stop"]:
            break
    p = handler_finalize(p)
    return p


def handler_init(p: dict) -> dict:
    """Initialize handler."""
    return p


def handler_check(p: dict) -> dict:
    """Check handler."""
    return p


def handler_process(p: dict) -> dict:
    """Process handler."""
    return p


def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
