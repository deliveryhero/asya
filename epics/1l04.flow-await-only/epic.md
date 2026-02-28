
      437  This ABI intentionally:
      438
      439  * treats `yield` as a syscall instruction
      338 -* uses three structural JSON verbs (GET/SET/DEL) that work on any node type
      339 -* avoids ambient mutable state (no globals, no imports from runtime)
      440 +* uses four verbs: three structural JSON verbs (GET/SET/DEL) + one streaming verb (FLY)
      441 +* separates control plane (tuples) from data plane (bare dicts)
      442 +* avoids ambient mutable state (no globals, no imports from runtime, no file I/O)
      443  * preserves linear, readable actor code
      444  * works identically in sync and async Python
      445
      343 -The ABI cannot be implemented using `await`, futures, callbacks, or context managers without losing correctn
          -ess or composability.
      446 +The ABI cannot be implemented using `await`, futures, callbacks, or context
      447 +managers without losing correctness or composability.
      448
      449 +### Why FLY instead of `partial: True`
      450 +
      451 +The previous convention mixed control signals with payload data:
      452 +
      453 +```python
      454 +# OLD: runtime must inspect every dict for "partial" key
      455 +yield {"partial": True, "token": "hello"}
      456 +```
      457 +
      458 +FLY makes the control signal structural (tuple type) not semantic (dict key):
      459 +
      460 +```python
      461 +# NEW: runtime dispatches on type, never inspects dict contents
      462 +yield "FLY", {"token": "hello"}
      463 +```
      464 +
      465 +This enables the runtime to be a pure instruction dispatcher — it routes
      466 +tuples as commands and dicts as payloads without ever looking inside them.
      467 +
      468  ---
      469
      347 -## 11. Reference mental model
      470 +## 12. Reference mental model
      471
      472  Think of an actor as a **userland process** and the runtime as a **kernel**.
      473
      351 -| Actor code                                  | Kernel analogue              |
      352 -| ------------------------------------------- | ---------------------------- |
      353 -| `yield "GET", "/route"`                     | `sys_read(ROUTE)`            |
      354 -| `yield "SET", "/route/next", ["a", "b"]`    | `sys_write(ROUTE_NEXT, val)` |
      355 -| `yield "DEL", "/headers/trace_id"`          | `sys_unlink(path)`           |
      356 -| `yield {"result": ...}`                     | `send_frame(downstream)`     |
      357 -| `yield {"token": ...}, True`                | `send_frame(upstream)`       |
      358 -| `yield from helper()`                       | inlined syscall macro        |
      474 +| Actor code                                    | Kernel analogue              |
      475 +| --------------------------------------------- | ---------------------------- |
      476 +| `yield "GET", ".route"`                       | `sys_read(ROUTE)`            |
      477 +| `yield "SET", ".route.next", ["a", "b"]`      | `sys_write(ROUTE_NEXT, val)` |
      478 +| `yield "SET", ".route.next[:0]", ["x"]`       | `sys_splice(ROUTE_NEXT, val)`|
      479 +| `yield "DEL", ".headers.trace_id"`            | `sys_unlink(path)`           |
      480 +| `yield {"result": ...}`                       | `send_frame(downstream)`     |
      481 +| `yield "FLY", {"token": ...}`                 | `send_frame(upstream)`       |
      482 +| `yield from helper()`                         | inlined syscall macro        |

● Now let me create the three new epics:

● Bash(mkdir -p /home/a.yushkovskiy/asya/.aint/epics/1l02.stream-replaces-partial
      /home/a.yushkovskiy/asya/.aint/epics/1l03.explicit-adapter-pattern /home/a.yushkovski…)
  ⎿  Done

● Write(.aint/epics/1l04.flow-await-only/epic.md)
  ⎿  Wrote 111 lines to .aint/epics/1l04.flow-await-only/epic.md
       1 ---
       2 title: "Flow DSL: only await, arbitrary payload names, no generator logic in flows"
       3 status: ideated
       4 priority: 1
       5 type: epic
---
title: "Flow DSL: only await, arbitrary payload names, no generator logic in flows"
status: ideated
priority: 1
type: epic
tags:
  - type:simplification
  - component:compiler
  - component:flow-dsl
dependencies:
  - 1l01
---

## Context

The previous design (ADR `adr.asya-csp-vs-adk-async-generator-for-agentic.md`)
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
