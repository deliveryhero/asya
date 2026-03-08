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

### Option A: ABI yield from the actor itself (immediately usable, no changes needed)

A generator handler reads a routing decision from the payload and writes the target
actor name via the ABI `SET` verb:

```python
async def llm_router(payload: dict):
    # LLM decides where to route based on conversation context
    target = payload.get("_transfer_to")
    if target:
        yield "SET", ".route.next[:0]", [target]  # prepend to existing route
    yield payload
```

Or in a dedicated dispatcher actor that executes after the LLM actor:

```python
async def dispatcher(payload: dict):
    target = payload.get("_transfer_to")
    if target:
        yield "SET", ".route.next", [target]  # replace entire remaining route
    yield payload
```

This is **already supported** by the ABI protocol (epic abi-instead-vfs, PR #239).
No compiler changes needed. The LLM actor sets `payload["_transfer_to"] = "billing_agent"`
in its response payload; the dispatcher (or the LLM actor itself as a generator) reads
it and sets `route.next` accordingly.

> **Note**: Option A previously referenced `/proc/asya/msg/route/next` (VFS, epic 1ixt).
> That approach is superseded. VFS was replaced by the ABI yield protocol.

### Option B: Flow DSL `transfer()` built-in

Extend the flow compiler to support a `transfer()` built-in that compiles to an ABI
`SET` yield:

```python
async def router_flow(state: dict) -> dict:
    state = await llm_router(state)
    transfer(state["_transfer_to"])  # dynamic route, validated at deploy time
```

The compiler generates a router that reads the target from the payload and emits
`yield "SET", ".route.next", [target]`. The `transfer()` call is a compile-time
marker — the generated router handles it at runtime.

Not yet supported. The compiler currently handles: mutations, conditionals (`if/elif/else`),
try/except, early returns, and actor calls. `transfer()` would be a new construct.
Tracked in support-more-compiler-constructs (not yet added).

### Option C: Router actor with enum validation

Generate a dispatcher router that validates the target against a configured set of
actor names, similar to ADK's enum constraint on `transfer_to_agent`:

```python
# Generated or hand-written router
VALID_TARGETS = set(filter(None, [
    os.environ.get("ASYA_HANDLER_BILLING"),
    os.environ.get("ASYA_HANDLER_TECH"),
]))

async def dispatch_router(payload: dict):
    target = payload.get("_transfer_to")
    if target not in VALID_TARGETS:
        raise ValueError(f"Invalid transfer target: {target!r}")
    yield "SET", ".route.next", [target]
    yield payload
```

The closed-world constraint prevents hallucinated routing to non-existent actors.
Can be combined with either Option A (hand-written dispatcher) or Option B (compiler
generates the enum check from deployed actor names).

## Recommendation

**Option A is immediately usable** — write a generator dispatcher actor using the ABI
protocol and deploy it. No framework changes required.

**Option C** adds safety on top of A. Implement the enum check in the hand-written
dispatcher actor.

**Option B** is the long-term ergonomic target for the flow compiler but is not
blocking. Add `transfer()` to support-more-compiler-constructs when prioritized.

## Acceptance Criteria (Option A)

- A generator actor can read `payload["_transfer_to"]` and emit
  `yield "SET", ".route.next", [target]` to dynamically route to a named actor
- An example or integration test demonstrates the pattern with at least two valid
  target actors
- Invalid targets routed to `x-sump` (normal error handling path)

## References

- survey-adk-data-flow.md Section 5.5 (transfer_to_agent), Section 8.2 (Gap 2)
- abi-instead-vfs summary (ABI protocol replaces VFS; supersedes epic 1ixt)
- docs/reference/abi-protocol.md (SET verb, path syntax)
- support-more-compiler-constructs (for Option B tracking)
- 1crb (traffic routing actor pipelines -- related routing patterns)
