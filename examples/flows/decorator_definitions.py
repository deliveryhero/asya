"""
Definition-site @actor and @inline decorators.

Functions decorated with @actor become queue boundaries (separate actors).
Functions decorated with @inline are inlined into the router code.
Unknown decorators on handler functions are ignored by the compiler.
"""

import uuid

from asya_lab.flow import flow


# Compiler classification hints — identity functions at runtime.
# The flow compiler recognises @actor and @inline on function definitions
# in the same file to classify each call without explicit wrappers.
def actor(f):
    return f


def inline(f):
    return f


@flow
def decorator_definitions_flow(p: dict) -> dict:
    p = inject_trace(p)
    p = validate(p)
    p = enrich(p)
    return p


@inline
def inject_trace(p: dict) -> dict:
    """Inject trace ID inline -- no actor boundary created."""
    p.setdefault("trace_id", str(uuid.uuid4()))
    return p


@actor
def validate(p: dict) -> dict:
    """Validate as a separate actor."""
    if "id" not in p:
        raise ValueError("missing required field: id")
    return p


@actor
def enrich(p: dict) -> dict:
    """Enrich as a separate actor."""
    p.setdefault("tags", [])
    return p
