"""
Mutations before and after handler.

Tests mutation grouping around handler calls.
"""


def mutations_before_after_handler_flow(p: dict) -> dict:
    p["step"] = 1
    p = handler_a(p)
    p["step"] = 2
    p = handler_b(p)
    p["step"] = 3
    return p


def handler_a(p: dict) -> dict:
    """Handler A."""
    return p


def handler_b(p: dict) -> dict:
    """Handler B."""
    return p
