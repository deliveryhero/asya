"""
If with empty branches.

Tests conditionals with pass statements (no handlers in branches).
"""


def if_empty_branches_flow(p: dict) -> dict:
    p = handler_setup(p)
    if p["skip_processing"]:
        pass
    else:
        pass
    p = handler_finalize(p)
    return p


def handler_setup(p: dict) -> dict:
    """Setup handler."""
    return p


def handler_process(p: dict) -> dict:
    """Process handler."""
    return p


def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
