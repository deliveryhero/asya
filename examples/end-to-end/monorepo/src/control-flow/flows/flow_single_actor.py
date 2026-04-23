"""
Single-actor flow — no router needed.

When a flow has exactly one actor call with no mutations or branching,
the compiler skips generating a start router entirely. The actor itself
becomes the flow entrypoint and should carry these Kubernetes labels:

    asya.sh/flow: single_actor_flow
    asya.sh/role: start

This eliminates a redundant actor hop compared to wrapping the actor
in a start router that only prepends it to the route.
"""

from _asya_utils import actor, flow


@flow
def single_actor_flow(p: dict) -> dict:
    p = document_processor(p)
    return p


@actor
def document_processor(p: dict) -> dict:
    """Process the document payload."""
    return p
