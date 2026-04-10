"""
Nested while loops.

Tests two-level loop nesting.
"""

from _asya_utils import actor, flow


@flow
def while_nested_flow(p: dict) -> dict:
    p = handler_init(p)
    p["i"] = 0
    while p["i"] < p["max_i"]:
        p["i"] += 1
        p = handler_outer(p)
        p["j"] = 0
        while p["j"] < p["max_j"]:
            p["j"] += 1
            p = handler_inner(p)
        p = handler_outer_end(p)
    p = handler_finalize(p)
    return p


@actor
def handler_init(p: dict) -> dict:
    """Initialize handler."""
    return p


@actor
def handler_outer(p: dict) -> dict:
    """Outer loop handler."""
    return p


@actor
def handler_inner(p: dict) -> dict:
    """Inner loop handler."""
    return p


@actor
def handler_outer_end(p: dict) -> dict:
    """Outer loop end handler."""
    return p


@actor
def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
