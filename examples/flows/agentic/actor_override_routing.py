"""
Actor Override Routing - flow with actor-level route overrides.

Demonstrates two override patterns:

1. SET (overwrite) - yield "SET", ".route.next", ["target"]
   Replaces the entire route. The message leaves the flow and goes
   directly to the target, breaking flow composition. Shown as a
   dashed red edge in the graph.

2. Prepend - yield "SET", ".route.next[:0]", ["target"]
   Inserts at the front of the route. The message visits the target
   first, then continues with the rest of the flow. Shown as a
   solid red edge in the graph.

Pattern: flow routing + actor-level yield SET override
"""
from asya_lab.flow import flow


@flow
async def actor_override_flow(p: dict) -> dict:
    p = await classify(p)

    if p.get("needs_tool"):
        p = await tool_executor(p)

    p = await format_output(p)
    return p


async def classify(p: dict) -> dict:
    """Classify intent and decide routing.

    Demonstrates both override patterns:
    - urgent: SET overwrites route to escalate (exits flow)
    - audit: prepend inserts audit_logger before continuing flow
    """
    if p.get("urgent"):
        yield "SET", ".route.next", ["escalate"]
        yield p
    else:
        yield "SET", ".route.next[:0]", ["audit_logger"]

    yield p


async def tool_executor(p: dict) -> dict:
    """Execute the requested tool."""
    p["tool_result"] = "executed"
    return p


async def format_output(p: dict) -> dict:
    """Format the final response."""
    p["formatted"] = True
    return p


async def escalate(p: dict) -> dict:
    """Handle urgent escalation (SET override target, exits flow)."""
    p["escalated"] = True
    return p


async def audit_logger(p: dict) -> dict:
    """Log for audit (prepend override target, continues flow)."""
    p["audited"] = True
    return p
