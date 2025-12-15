"""
If inside while loop.

Tests conditional branching within iteration.
"""


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


def handler_init(p: dict) -> dict:
    """Initialize handler."""
    return p


def handler_even(p: dict) -> dict:
    """Even iteration handler."""
    return p


def handler_odd(p: dict) -> dict:
    """Odd iteration handler."""
    return p


def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
