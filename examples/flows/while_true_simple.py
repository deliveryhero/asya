"""
While True with break.

Tests infinite loop with conditional exit.
"""


def while_true_flow(p: dict) -> dict:
    p = handler_init(p)
    while True:
        p = handler_process(p)
        if p.get("done", False):
            break
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
