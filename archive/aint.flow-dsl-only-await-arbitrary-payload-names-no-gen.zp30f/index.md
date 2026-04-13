---
title: "Flow DSL: only await, arbitrary payload names, no generator logic in flows"
status: merged
priority: 2
---

## Context

The previous design (ADR `.aint/epics/1c8d.agentic-umbrella/adr.asya-csp-vs-adk-async-generator-for-agentic.md`)
proposed two actor-call syntaxes in the flow DSL:

1. `state = await actor(state)` — 1-to-1
2. `state["events"].extend(event async for event in actor(state))` — 1-to-N-to-1

This created complexity: the compiler needed to generate setup routers, body
routers, and fan-in aggregators for the `async for` pattern.

## Decision

**Flows use only `await`.** All generator/streaming/ABI complexity stays inside
actors. The flow's only responsibility is control flow (sequencing, branching,
looping) and router generation.

```python
# Flow — dead simple
async def react_agent(state: dict) -> dict:
    while True:
        state = await llm(state)           # always 1-to-1
        if not state["events"][-1].get("tool_calls"):
            break
        state = await tool_executor(state)  # always 1-to-1
    return state
```

The `llm` handler internally handles streaming (FLY), event accumulation, and
ABI interactions. The flow doesn't know or care.

## Changes

### Arbitrary payload parameter names

Currently the compiler requires `p` or `payload`. Allow any name:

```python
async def my_flow(state: dict) -> dict:    # "state" instead of "p"
    state = await step_one(state)
    return state

async def other_flow(ctx: dict) -> dict:   # "ctx" — user's choice
    ctx = await process(ctx)
    return ctx
```

The compiler infers the parameter name from the function signature.

### Fan-out remains on flow level

Fan-out (parallel execution) stays as a flow-level construct for explicit cases:

```python
async def parallel_flow(state: dict) -> dict:
    results = await asyncio.gather(
        branch_a(state),
        branch_b(state),
    )
    # fan-in logic...
    return state
```

### Compiler teaching about custom decorators

Users may write `@actor_handler` style decorators (not provided by Asya) to
turn generators into coroutines for local testing:

```python
@actor_handler  # user-written decorator
async def llm(state):
    yield "FLY", {"token": "..."}
    state["events"].append(...)
    yield state

# In flow: state = await llm(state)  # works locally via decorator
# Deployed: runtime calls llm.__wrapped__ (bare generator)
```

The compiler needs to understand that `await actor_wrapper(handler(state))`
or `await handler(state)` (where handler is decorated) both compile to the
same actor call. Exact mechanism TBD — may inspect `__wrapped__` or require
explicit registration.

### Max fanout protection (env var)

`ASYA_MAX_FANOUT` — enforced by the runtime. Default: no limit. When the
compiler generates flow actors, it sets `ASYA_MAX_FANOUT=1` to protect 1-to-1
message semantics. Prevents accidental fan-out from generator actors inside flows.

The runtime counts downstream EMIT yields. If count exceeds `ASYA_MAX_FANOUT`,
raise a protocol error.

## Supersedes

- ADR section on `async for` accumulation semantics (Section 3, 4, 6)
- ADR section on body routers and fan-in for event accumulation
- The `AsyncForAccumulate` IR node (never built)
