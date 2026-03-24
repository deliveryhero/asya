"""
If with empty branches.

Tests conditionals with pass statements (no handlers in branches).
"""

from _asya_utils import actor, flow


@flow
def if_one_empty_branch_flow(p: dict) -> dict:
    p = handler_setup(p)
    if p["skip_processing"]:
        pass
    else:
        p = handler_process(p)
    p = handler_finalize(p)
    return p


@actor
def handler_setup(p: dict) -> dict:
    """Setup handler."""
    return p


@actor
def handler_process(p: dict) -> dict:
    """Process handler."""
    return p


@actor
def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
