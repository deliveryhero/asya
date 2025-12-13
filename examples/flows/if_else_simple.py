"""
Simple if-else.

Tests basic two-branch conditional.
"""


def if_else_simple_flow(p: dict) -> dict:
    p = handler_setup(p)
    if p["type"] == "A":
        p = handler_type_a(p)
    else:
        p = handler_type_b(p)
    p = handler_finalize(p)
    return p


def handler_setup(p: dict) -> dict:
    """Setup handler."""
    return p


def handler_type_a(p: dict) -> dict:
    """Type A handler."""
    return p


def handler_type_b(p: dict) -> dict:
    """Type B handler."""
    return p


def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
