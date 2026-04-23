"""
Dynamic routing - LLM decides the next actor at runtime.

Asya equivalent of ADK's transfer_to_agent. Uses the ABI yield protocol
to replace route.next with the LLM's chosen target actor at runtime,
instead of relying on static conditions compiled into router actors.

Two variants are shown:

  1. Dispatcher actor (separate from LLM): reads _transfer_to from payload,
     validates against known targets, and sets route.next.

  2. Self-routing LLM actor: the LLM call and routing decision happen in the
     same actor, skipping the dispatcher hop.

The enum validation against ASYA_HANDLER_* env vars prevents the LLM from
hallucinating non-existent actor names.

Deploy:
  ASYA_HANDLER=dynamic_routing.dispatcher
  ASYA_HANDLER_BILLING=asya-prod-billing-agent
  ASYA_HANDLER_TECH=asya-prod-tech-support
  ASYA_HANDLER_DEFAULT=asya-prod-general-agent

See also:
  docs/tutorials/agentic-patterns.md (Pattern 1: Dynamic routing)
  docs/reference/abi-protocol.md (SET verb)
"""

import os

# Allowlist of valid routing targets, built from ASYA_HANDLER_* env vars.
# Each env var maps a logical name (lowercased suffix) to a queue/actor name.
# Example: ASYA_HANDLER_BILLING=asya-prod-billing-agent -> "billing" -> "asya-prod-billing-agent"
VALID_TARGETS = {
    key.removeprefix("ASYA_HANDLER_").lower(): queue
    for key, queue in os.environ.items()
    if key.startswith("ASYA_HANDLER_")
}


# --- Variant 1: Dedicated dispatcher actor ---


async def dispatcher(payload: dict):
    """Dispatcher actor: reads _transfer_to from payload and sets route.next.

    The upstream LLM actor sets payload["_transfer_to"] = "billing" (a logical
    name). This actor resolves the logical name to a queue name and rewrites
    the route. Unknown targets raise ValueError (routed to x-sump).

    Deploy as: ASYA_HANDLER=dynamic_routing.dispatcher
    """
    target_key = payload.pop("_transfer_to", None)

    if not target_key:
        # No routing decision; continue with the pre-configured route.next
        yield payload
        return

    # Enum validation: always require target to be in allowlist.
    # VALID_TARGETS is empty when no ASYA_HANDLER_* env vars are set,
    # which means dynamic routing is unconfigured — always raise in that case.
    if target_key not in VALID_TARGETS:
        raise ValueError(
            f"Invalid transfer target: {target_key!r}. "
            f"Valid targets: {sorted(VALID_TARGETS)}. "
            f"Configure ASYA_HANDLER_<NAME>=<queue> env vars to define valid targets."
        )
    actor_name = VALID_TARGETS[target_key]

    yield "SET", ".route.next", [actor_name]
    yield payload


# --- Variant 2: Self-routing LLM actor ---


async def llm_router(payload: dict):
    """LLM actor that decides routing as part of its own processing.

    Avoids the dispatcher hop by combining the LLM call and the routing
    decision in one actor. The LLM response determines which actor handles
    the payload next.

    Deploy as: ASYA_HANDLER=dynamic_routing.llm_router
    """
    target_key, response = await _call_llm_with_routing(payload)

    payload["response"] = response

    if target_key:
        actor_name = VALID_TARGETS.get(target_key)
        if actor_name is None:
            raise ValueError(
                f"LLM returned unknown routing target: {target_key!r}. "
                f"Valid targets: {sorted(VALID_TARGETS)}. "
                f"Configure ASYA_HANDLER_<NAME>=<queue> env vars to define valid targets."
            )
        yield "SET", ".route.next", [actor_name]

    yield payload


# --- Mock LLM implementations ---


async def _call_llm_with_routing(payload: dict) -> tuple[str | None, str]:
    """Mock LLM router. Replace with a real LLM call.

    Returns (target_key, response_text). target_key is a logical name
    matching an ASYA_HANDLER_* env var suffix (lowercase), or None to
    keep the existing route.

    Real implementation (Anthropic):

        import anthropic

        client = anthropic.AsyncAnthropic()
        tools = [{"name": "transfer_to", "input_schema": {
            "type": "object",
            "properties": {"target": {"type": "string", "enum": list(VALID_TARGETS)}},
            "required": ["target"],
        }}]
        msg = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            tools=tools,
            messages=[{"role": "user", "content": payload.get("query", "")}],
        )
        for block in msg.content:
            if block.type == "tool_use" and block.name == "transfer_to":
                return block.input["target"], ""
        return None, msg.content[0].text
    """
    query = payload.get("query", "").lower()
    if any(word in query for word in ("billing", "invoice", "payment", "charge")):
        return "billing", "Routing to billing agent."
    if any(word in query for word in ("error", "crash", "technical", "bug")):
        return "tech", "Routing to technical support."
    return "default", "Routing to general agent."
