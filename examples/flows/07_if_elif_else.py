"""
If-elif-else chain.

Tests multi-branch conditional routing.
"""


def if_elif_else_flow(p: dict) -> dict:
    p = handler_validate(p)
    if p["type"] == "A":
        p = handler_type_a(p)
    elif p["type"] == "B":
        p = handler_type_b(p)
    else:
        p = handler_default(p)
    p = handler_finalize(p)
    return p


def handler_validate(p: dict) -> dict:
    """Validation handler."""
    return p


def handler_type_a(p: dict) -> dict:
    """Type A handler."""
    return p


def handler_type_b(p: dict) -> dict:
    """Type B handler."""
    return p


def handler_default(p: dict) -> dict:
    """Default handler."""
    return p


def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
