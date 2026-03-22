"""
Early return in conditional.

Tests early exit pattern for error handling.
"""

from _asya_utils import actor, flow


@flow
def early_return_flow(p: dict) -> dict:
    p = handler_validate(p)
    if not p["valid"]:
        p = handler_error(p)
        return p
    p = handler_process(p)
    p = handler_finalize(p)
    return p


@actor
def handler_validate(p: dict) -> dict:
    """Validation handler."""
    return p


@actor
def handler_error(p: dict) -> dict:
    """Error handler."""
    return p


@actor
def handler_process(p: dict) -> dict:
    """Process handler."""
    return p


@actor
def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
