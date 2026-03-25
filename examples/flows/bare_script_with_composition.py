"""
Bare-script flow that composes another flow via function call.

Demonstrates:
- # asya: flow on function definition (no decorator import)
- Flow composition: sub_flow is defined with # asya: flow and called
  from main_flow — the compiler inlines its body
- Mixed: some actors via # asya: actor, sub-flow via # asya: flow call
"""


def validate(p: dict) -> dict:  # asya: actor
    """Validate input has required fields."""
    p.setdefault("text", "")
    p["validated"] = True
    return p


def enrich(p: dict) -> dict:  # asya: actor
    """Add metadata to the payload."""
    p["word_count"] = len(p.get("text", "").split())
    return p


def format_output(p: dict) -> dict:  # asya: actor
    """Format the final output."""
    p["formatted"] = True
    return p


def sub_flow(p: dict) -> dict:  # asya: flow
    """Sub-flow: validate then enrich. Inlined when called from main_flow."""
    p = validate(p)  # asya: actor
    p = enrich(p)    # asya: actor
    return p


def main_flow(p: dict) -> dict:  # asya: flow
    """Main flow: runs sub_flow (inlined) then formats output."""
    p = sub_flow(p)       # asya: flow  (compiler inlines validate -> enrich)
    p = format_output(p)  # asya: actor
    return p
