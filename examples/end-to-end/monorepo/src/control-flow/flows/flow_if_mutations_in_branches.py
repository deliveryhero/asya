"""
If with mutations in branches.

Tests mutations mixed with handlers in conditionals.
"""

from _asya_utils import actor, flow


@flow
def if_mutations_in_branches_flow(p: dict) -> dict:
    p = handler_setup(p)
    if p["type"] == "A":
        p["branch"] = "A"
        p["value"] = 100
        p = handler_type_a(p)
    else:
        p = handler_type_b(p)
        p["branch"] = "B"
        p["value"] = 200
    p = handler_finalize(p)
    return p


@actor
def handler_setup(p: dict) -> dict:
    """Setup handler."""
    return p


@actor
def handler_type_a(p: dict) -> dict:
    """Type A handler."""
    return p


@actor
def handler_type_b(p: dict) -> dict:
    """Type B handler."""
    return p


@actor
def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
