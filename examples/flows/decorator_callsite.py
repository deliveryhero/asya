"""
Call-site decoration pattern: actor(handler)(p) and inline(fn)(p).

Equivalent to definition-site @actor / @inline decorators,
applied at the call site for functions defined outside this file.
stamp_timestamp runs inline in the router (no queue boundary).
validator and enricher are separate actors.
"""

import time


# Compiler classification hints — identity functions at runtime.
# The flow compiler recognises these names to classify calls:
#   actor(fn)(p)  -> queue boundary (separate actor)
#   inline(fn)(p) -> inlined into the router (no queue hop)
def actor(f):
    return f


def inline(f):
    return f


def decorator_callsite_flow(p: dict) -> dict:
    p = inline(stamp_timestamp)(p)
    p = actor(validator)(p)
    p = actor(enricher)(p)
    return p


def stamp_timestamp(p: dict) -> dict:
    """Stamp current timestamp inline in the router."""
    p["ts"] = time.time()
    return p


def validator(p: dict) -> dict:
    """Validate payload as a separate actor."""
    if "id" not in p:
        raise ValueError("missing required field: id")
    return p


def enricher(p: dict) -> dict:
    """Enrich payload as a separate actor."""
    p.setdefault("tags", [])
    return p
