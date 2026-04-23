"""
Inline comment overrides for compiler rules.

Demonstrates # asya: <action> directives for per-statement control
over how the flow compiler classifies each operation.

Syntax follows standard Python tool conventions (# type: ignore, # noqa: E501):
  # asya: <action>

Supported actions:
  actor    — dispatch to actor queue (default for p = call(p))
  inline   — embed in router code; the call executes inside the router,
             not dispatched to a separate actor queue

Priority order:
  1. Inline comment (# asya: <action>)  <- highest
  2. Compiler rule from asya.yaml
  3. Default resolution
"""

from _asya_utils import actor, flow


@flow
def order_pipeline(p: dict) -> dict:
    # inline: fast local normalization, no actor queue needed
    p = normalize_keys(p)  # asya: inline

    # actor: explicit dispatch (default behavior, shown for documentation)
    p = validate_order(p)  # asya: actor

    if p.get("fraud_score", 0) > 0.8:
        p["status"] = "rejected"
        return p

    p = charge_payment(p)
    return p


# Helper functions — deployed as actors or inlined depending on the directive


@actor
def normalize_keys(p: dict) -> dict:
    """Normalize payload keys to lowercase — runs inline in the router."""
    return {k.lower(): v for k, v in p.items()}


@actor
def validate_order(p: dict) -> dict:
    """Validate order fields — dispatched to its own actor queue."""
    return p


@actor
def charge_payment(p: dict) -> dict:
    """Payment processing — dispatched to its own actor queue."""
    return p
