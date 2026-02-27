---
title: "Compiler: reject async-for / yield-from across actor boundaries"
priority: 3 # low
type: task
---

The Flow DSL compiler must detect and reject patterns that attempt to
re-yield partial events across actor boundaries.

## Patterns to Reject

### 1. `async for ... yield` (re-yielding partials)

```python
# FORBIDDEN -- compiler must reject
async for event in agent_llm(prompt):
    yield event  # Cannot forward partials through queues
```

**Reason**: Partial events are transport-level (HTTP direct from sidecar to
gateway) and cannot flow through message queues. See 1ia4 RFC Section 2.

### 2. `yield from` (delegation across actor boundary)

```python
# FORBIDDEN -- compiler must reject at flow level
yield from agent_llm(prompt)
```

**Reason**: The 1ia4 RFC (Section 2) initially said `yield from` is "ALLOWED"
because the callee actor's sidecar handles upstream events directly. However,
this is only true for **upstream (partial)** events. The callee also produces
**downstream** events that must enter the queue for the next actor. At the flow
level, `yield from` would require dual-routing (upstream to gateway AND downstream
to next actor from the same callee), which the sidecar does not support.

**Clarification**: `yield from` is fine **inside a handler** (single actor,
not compiled by the flow compiler). The compiler only needs to reject it in
flow definitions where it would cross actor boundaries.

### 3. ADK patterns that are fine WITHOUT compiler involvement

The ADK ReAct loop pattern (`async for event in llm_call(state)`) works
**inside a single actor handler** -- it never crosses actor boundaries:

```python
# This is a HANDLER, not a flow definition -- no compiler involvement
async def agent_with_tools(state: dict) -> AsyncGenerator[dict, None]:
    while True:
        async for event in llm_call(state):
            if event.get("tool_calls"):
                state = await execute_tools(state, event["tool_calls"])
        yield state
```

The runtime already supports async generators (task 1f2wwf, vibed).
The sidecar already parses SSE frames (task 1in0hv, vibed).

## Implementation

- In the flow compiler parser (src/asya-cli/), detect `ast.AsyncFor` and
  `ast.YieldFrom` nodes
- Emit a clear compile-time error explaining why this is not supported
- Error message should suggest: "Use `state = await actor(state)` for
  actor calls. Streaming happens transparently via the sidecar."
- Add unit tests for the rejection

## References

- 1ia4 RFC Section 2 (transport-level partial events)
- 1irj RFC Section 4 (async-for-yield CPS analysis -- note: Phase 4 is
  STALE, it references the rejected ASYA_PARTIAL_EVENTS_ROUTE design)
- survey-adk-data-flow.md (ADK event types, partial vs non-partial)
