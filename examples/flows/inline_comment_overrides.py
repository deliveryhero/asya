"""
Inline comment overrides for compiler rules.

Demonstrates # asya: treat-as-* directives for per-statement control
over how the flow compiler classifies each operation.

Priority order:
  1. Inline comment (# asya: treat-as-*)  ← highest
  2. Compiler rule from asya.yaml
  3. Default resolution

Supported actions:
  actor    — dispatch to actor queue (default for p = call(p))
  inline   — embed in router code, not dispatched to queue
"""


def order_pipeline(p: dict) -> dict:
    # treat-as-inline: fast local util, no actor queue needed
    p = normalize_keys(p)  # asya: treat-as-inline

    # treat-as-actor: explicit dispatch even if compiler would inline it
    p = validate_order(p)  # asya: treat-as-actor

    # treat-as-actor with name override: rename the actor in the route
    p = run_fraud_check(p)  # asya: treat-as-actor name=fraud-detection-v2

    if p.get("fraud_score", 0) > 0.8:
        p["status"] = "rejected"
        return p

    p = charge_payment(p)
    return p


# Helper functions used by the flow (would be deployed as actors or inline utils)

def normalize_keys(p: dict) -> dict:
    """Normalize payload keys to lowercase — runs inline in the router."""
    return {k.lower(): v for k, v in p.items()}


def validate_order(p: dict) -> dict:
    """Validate order fields — dispatched to its own actor queue."""
    return p


def run_fraud_check(p: dict) -> dict:
    """Fraud detection — routed to 'fraud-detection-v2' actor queue."""
    return p


def charge_payment(p: dict) -> dict:
    """Payment processing — dispatched to its own actor queue."""
    return p
