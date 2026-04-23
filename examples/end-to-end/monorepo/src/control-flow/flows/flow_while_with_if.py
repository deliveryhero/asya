"""
If inside while loop.

Tests conditional branching within iteration.
"""

from _asya_utils import actor, flow


@flow
def if_inside_while_flow(p: dict) -> dict:
    p = handler_init(p)
    p["i"] = 0
    while p["i"] < p["max_iterations"]:
        p["i"] += 1
        if p["i"] % 2 == 0:
            p = handler_even(p)
        else:
            p = handler_odd(p)
    p = handler_finalize(p)
    return p


@actor
def handler_init(p: dict) -> dict:
    """Initialize handler."""
    return p


@actor
def handler_even(p: dict) -> dict:
    """Even iteration handler."""
    return p


@actor
def handler_odd(p: dict) -> dict:
    """Odd iteration handler."""
    return p


@actor
def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
