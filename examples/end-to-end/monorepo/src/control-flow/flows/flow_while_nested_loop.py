"""
Loop processing flow example.

Demonstrates while loops with break and continue statements.
"""

from _asya_utils import actor, flow


@flow
def nested_loop_flow(p: dict) -> dict:
    p = initialize(p)

    p["i"] = 0
    while p["i"] < p["max_i"]:
        p["i"] += 1
        p["j"] = 0
        while p["j"] < p["max_j"]:
            p["j"] += 1
            p = process_item(p)
        p = finalize_loop_j(p)
    p = finalize_loop_i(p)
    return p


@actor
def process_item(p: dict) -> dict:
    return p


@actor
def finalize_loop_j(p: dict) -> dict:
    """Initialize processing state."""
    p["finalize_loop_j"] = 1
    return p


@actor
def finalize_loop_i(p: dict) -> dict:
    """Process single iteration."""
    p["finalize_loop_i"] = 1
    return p
