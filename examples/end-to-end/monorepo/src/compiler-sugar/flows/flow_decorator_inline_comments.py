"""
Inline comment directives for compiler classification.

Demonstrates # asya: inline and # asya: actor overrides.
inject_id runs inline in the router (no actor boundary).
classifier is explicitly marked as an actor boundary.
"""

import uuid

from _asya_utils import actor, flow


@flow
def decorator_inline_comments_flow(p: dict) -> dict:
    p = inject_id(p)  # asya: inline
    p = classifier(p)  # asya: actor
    if p["category"] == "priority":
        p = fast_handler(p)
    else:
        p = standard_handler(p)
    return p


@actor
def inject_id(p: dict) -> dict:
    """Inject a unique ID inline in the router, not a separate actor."""
    p.setdefault("id", str(uuid.uuid4()))
    return p


@actor
def classifier(p: dict) -> dict:
    """Classify message as a separate actor."""
    p.setdefault("category", "standard")
    return p


@actor
def fast_handler(p: dict) -> dict:
    """Handle priority messages."""
    p["handled_by"] = "fast"
    return p


@actor
def standard_handler(p: dict) -> dict:
    """Handle standard messages."""
    p["handled_by"] = "standard"
    return p
