"""
If statement without else.

Tests conditional with only true branch.
"""

from _asya_utils import actor, flow


@flow
def if_no_else_flow(p: dict) -> dict:
    p = handler_setup(p)
    if p["condition"]:
        p = handler_true(p)
    return p


@actor
def handler_setup(p: dict) -> dict:
    """Setup handler."""
    return p


@actor
def handler_true(p: dict) -> dict:
    """True branch handler."""
    return p


@actor
def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
