"""
Conditional routing flow example.

Demonstrates if/elif/else branching based on payload data.
"""


def conditional_flow(p: dict) -> dict:
    p = handler_validate_input(p)

    if p["type"] == "A":
        p = handler_type_a(p)
        p["mut"] = "A"
    elif p["type"] == "B":
        p = handler_type_b(p)
        p["mut"] = "B"
    else:
        p = handler_type_default(p)
        p["mut"] = "default"

    p = handler_finalize(p)
    return p


def handler_validate_input(p: dict) -> dict:
    """Mock validation handler."""
    p["validated"] = True
    return p


def handler_type_a(p: dict) -> dict:
    """Handler for type A data."""
    p["handler"] = "type_a"
    return p


def handler_type_b(p: dict) -> dict:
    """Handler for type B data."""
    p["handler"] = "type_b"
    return p


def handler_type_c(p: dict) -> dict:
    """Handler for type C data."""
    p["handler"] = "type_c"
    return p


def handler_default(p: dict) -> dict:
    """Default handler."""
    p["handler"] = "default"
    return p


def handler_finalize(p: dict) -> dict:
    """Mock finalizer handler."""
    p["finalized"] = True
    return p
