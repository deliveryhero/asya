"""
Mutations followed by handler.

Tests grouping mutations before handler calls.
"""


def mutations_with_handler_flow(p: dict) -> dict:
    p["initialized"] = True
    p["step"] = 1
    p["count"] = 0
    p = handler_process(p)
    p["finalized"] = True
    return p


def handler_process(p: dict) -> dict:
    """Process handler."""
    return p
