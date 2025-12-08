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


def flow_conditional_routing(payload: dict) -> dict:
    payload = handler_validate_input(payload)

    if payload["type"] == "A":
        payload = handler_type_a(payload)
    elif payload["type"] == "B":
        payload = handler_type_b(payload)
    elif payload["type"] == "C":
        payload = handler_type_c(payload)
    else:
        payload = handler_default(payload)

    payload = handler_finalize(payload)
    return payload

def handler_validate_input(payload: dict) -> dict:
    """Mock validation handler."""
    payload["validated"] = True
    return payload


def handler_type_a(payload: dict) -> dict:
    """Handler for type A data."""
    payload["handler"] = "type_a"
    return payload


def handler_type_b(payload: dict) -> dict:
    """Handler for type B data."""
    payload["handler"] = "type_b"
    return payload


def handler_type_c(payload: dict) -> dict:
    """Handler for type C data."""
    payload["handler"] = "type_c"
    return payload


def handler_default(payload: dict) -> dict:
    """Default handler."""
    payload["handler"] = "default"
    return payload


def handler_finalize(payload: dict) -> dict:
    """Mock finalizer handler."""
    payload["finalized"] = True
    return payload
