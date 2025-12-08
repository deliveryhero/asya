"""
Conditional routing flow example.

Demonstrates if/elif/else branching based on payload data.

When deploying compiled routers, set environment variables:
    ASYA_HANDLER_INPUT_VALIDATOR="examples.flows.conditional_routing.handler_validate_input"
    ASYA_HANDLER_TYPE_A_PROCESSOR="examples.flows.conditional_routing.handler_type_a"
    ASYA_HANDLER_TYPE_B_PROCESSOR="examples.flows.conditional_routing.handler_type_b"
    ASYA_HANDLER_TYPE_C_PROCESSOR="examples.flows.conditional_routing.handler_type_c"
    ASYA_HANDLER_DEFAULT_PROCESSOR="examples.flows.conditional_routing.handler_default"
    ASYA_HANDLER_FINALIZER="examples.flows.conditional_routing.handler_finalize"
"""


def conditional_scene(p: dict) -> dict:
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
