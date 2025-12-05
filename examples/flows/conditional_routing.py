"""
Conditional routing flow example.

Demonstrates if/elif/else branching based on payload data.
"""

from typing import Dict


def validate_input(p: Dict) -> Dict:
    """Mock validation handler."""
    p["validated"] = True
    return p


def handle_type_a(p: Dict) -> Dict:
    """Handler for type A data."""
    p["handler"] = "type_a"
    return p


def handle_type_b(p: Dict) -> Dict:
    """Handler for type B data."""
    p["handler"] = "type_b"
    return p


def handle_type_c(p: Dict) -> Dict:
    """Handler for type C data."""
    p["handler"] = "type_c"
    return p


def handle_default(p: Dict) -> Dict:
    """Default handler."""
    p["handler"] = "default"
    return p


def finalize(p: Dict) -> Dict:
    """Mock finalizer handler."""
    p["finalized"] = True
    return p


def flow_conditional_routing(p: Dict) -> Dict:
    p = validate_input(p)

    if p["type"] == "A":
        p = handle_type_a(p)
    elif p["type"] == "B":
        p = handle_type_b(p)
    elif p["type"] == "C":
        p = handle_type_c(p)
    else:
        p = handle_default(p)

    p = finalize(p)
    return p
