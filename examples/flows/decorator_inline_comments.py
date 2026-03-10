"""
Inline comment directives for compiler classification.

Demonstrates # asya: inline and # asya: actor overrides.
inject_id runs inline in the router (no actor boundary).
classifier is explicitly marked as an actor boundary.
"""

import uuid


def decorator_inline_comments_flow(p: dict) -> dict:
    p = inject_id(p)           # asya: inline
    p = classifier(p)          # asya: actor
    if p["category"] == "priority":
        p = fast_handler(p)
    else:
        p = standard_handler(p)
    return p


def inject_id(p: dict) -> dict:
    """Inject a unique ID inline in the router, not a separate actor."""
    p.setdefault("id", str(uuid.uuid4()))
    return p


def classifier(p: dict) -> dict:
    """Classify message as a separate actor."""
    p.setdefault("category", "standard")
    return p


def fast_handler(p: dict) -> dict:
    """Handle priority messages."""
    p["handled_by"] = "fast"
    return p


def standard_handler(p: dict) -> dict:
    """Handle standard messages."""
    p["handled_by"] = "standard"
    return p
