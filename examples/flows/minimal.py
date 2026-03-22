"""
Minimal flow - single handler.

Tests the simplest possible flow compilation.
"""

from _asya_utils import actor, flow


@flow
def minimal_flow(p: dict) -> dict:
    p = handler_a(p)
    return p


@actor
def handler_a(p: dict) -> dict:
    """Single handler."""
    return p
