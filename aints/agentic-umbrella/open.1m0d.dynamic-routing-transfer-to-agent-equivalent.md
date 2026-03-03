---
title: "Dynamic routing: transfer_to_agent equivalent for LLM-decided actor selection"
priority: 2 # medium
tags:
  - type:feature
---

Implement runtime dynamic routing where the LLM decides which actor to hand off
to, equivalent to ADK's `transfer_to_agent` pattern.

## ADK Pattern

In ADK, an LlmAgent with sub-agents automatically gets a `transfer_to_agent`
tool injected. The LLM calls it to route to a sub-agent at runtime:

```python
# ADK: LLM calls transfer_to_agent("BillingAgent")
# -> sets event.actions.transfer_to_agent = "BillingAgent"
# -> Runner routes to BillingAgent on next turn
```

The target is constrained to an enum of valid agent names, preventing hallucinated
routing. See survey-adk-data-flow.md Section 5.5 for full details.

## Current Asya Limitation

Asya's flow compiler generates **static conditional routers** from flow source:

```python
# Flow DSL -- static conditions compiled ahead of time
if state["type"] == "billing":
    state = await billing_agent(state)
elif state["type"] == "tech":
    state = await tech_support(state)
```

This requires the developer to enumerate all routing conditions at compile time.
ADK lets the LLM decide dynamically based on conversation context.

## Proposed Approaches

### Option A: Dispatcher actor via VFS route modification

A handler actor reads a routing decision from the payload and writes the target
actor name to `/proc/asya/msg/route/next`:

```python
async def dispatcher(state: dict) -> dict:
    target = state.get("_transfer_to")
    if target:
        with open("/proc/asya/msg/route/next", "w") as f:
            f.write(target)
    return state
```

- Already supported by the VFS (epic 1ixt)
- No compiler changes needed
- The LLM actor sets `state["_transfer_to"] = "billing_agent"` in its response

### Option B: Flow DSL syntax for dynamic routing

Extend the flow compiler to support a `transfer()` built-in:

```python
async def router_flow(state: dict) -> dict:
    state = await llm_router(state)
    transfer(state["_transfer_to"])  # dynamic route, validated at deploy time
```

The compiler generates a router that reads the target from the payload and
modifies `route.next` accordingly.

### Option C: Router actor with enum validation

Generate a dispatcher router that validates the target against a configured
set of actor names (from environment variables), similar to ADK's enum constraint:

```python
# Generated router
VALID_TARGETS = {
    os.environ["ASYA_HANDLER_BILLING"]: "billing",
    os.environ["ASYA_HANDLER_TECH"]: "tech_support",
}

def dispatch_router(message):
    target = message["payload"].get("_transfer_to")
    if target not in VALID_TARGETS:
        raise ValueError(f"Invalid transfer target: {target}")
    # modify route.next
```

## Recommendation

Option A is immediately usable (zero implementation needed). Option C adds
compile-time safety. Start with A, consider C for the compiler.

## References

- survey-adk-data-flow.md Section 5.5 (transfer_to_agent), Section 8.2 (Gap 2)
- epic 1ixt (message metadata VFS -- /proc/asya/msg/route/next)
- 1crb (traffic routing actor pipelines -- related routing patterns)
