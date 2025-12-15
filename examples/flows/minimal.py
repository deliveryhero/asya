"""
Minimal flow - single handler.

Tests the simplest possible flow compilation.
"""


def minimal_flow(p: dict) -> dict:
    p = handler_a(p)
    return p


def handler_a(p: dict) -> dict:
    """Single handler."""
    return p
