"""
If statement without else.

Tests conditional with only true branch.
"""


def if_no_else_flow(p: dict) -> dict:
    p = handler_setup(p)
    if p["condition"]:
        p = handler_true(p)
    return p


def handler_setup(p: dict) -> dict:
    """Setup handler."""
    return p


def handler_true(p: dict) -> dict:
    """True branch handler."""
    return p


def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
