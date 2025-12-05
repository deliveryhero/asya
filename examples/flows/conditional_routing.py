"""
Conditional routing flow example.

Demonstrates if/elif/else branching based on payload data.
"""

from typing import Dict


def flow_conditional_routing(p: Dict) -> Dict:
    p = handler_validate_input(p)

    if p["type"] == "A":
        p = handler_type_a(p)
    elif p["type"] == "B":
        p = handler_type_b(p)
    elif p["type"] == "C":
        p = handler_type_c(p)
    else:
        p = handler_default(p)

    p = handler_finalize(p)
    return p

def handler_validate_input(p: Dict) -> Dict:
    """Mock validation handler."""
    p["validated"] = True
    return p


def handler_type_a(p: Dict) -> Dict:
    """Handler for type A data."""
    p["handler"] = "type_a"
    return p


def handler_type_b(p: Dict) -> Dict:
    """Handler for type B data."""
    p["handler"] = "type_b"
    return p


def handler_type_c(p: Dict) -> Dict:
    """Handler for type C data."""
    p["handler"] = "type_c"
    return p


def handler_default(p: Dict) -> Dict:
    """Default handler."""
    p["handler"] = "default"
    return p


def handler_finalize(p: Dict) -> Dict:
    """Mock finalizer handler."""
    p["finalized"] = True
    return p
