"""
Pure sequential flow - no control structures.

Tests sequential handler execution without any branching or loops.
"""


def sequential_flow(p: dict) -> dict:
    p = handler_a(p)
    p = handler_b(p)
    p = handler_c(p)
    return p


def handler_a(p: dict) -> dict:
    """First handler."""
    return p


def handler_b(p: dict) -> dict:
    """Second handler."""
    return p


def handler_c(p: dict) -> dict:
    """Third handler."""
    return p
