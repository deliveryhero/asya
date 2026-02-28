---
title: "Explicit adapter functions instead of ASYA_PARAMS_AT/ASYA_RESULT_AT"
status: ideated
priority: 2
type: epic
tags:
  - type:simplification
  - component:runtime
  - component:docs
---

## Context

PR 235 (`1ixz/phase1-typed-signatures`) adds `ASYA_PARAMS_AT` and `ASYA_RESULT_AT`
environment variables to the runtime for automatic input extraction and output
merging. This adds ~600 lines of framework code for something users can do
explicitly in ~10 lines of Python.

At this stage of the framework, **explicit is better than implicit**. Users write
adapter functions that map between the protocol (`dict → dict`) and their domain
types. This is more transparent, more testable, and lets patterns emerge from
real usage before we bake them into the framework.

## Decision

- Close PR 235 without merging
- Close all tasks in epic 1ixz (typed handler signatures)
- Document the adapter pattern in tutorials as the recommended approach

## Adapter Pattern

```python
from myapp.models import Foo, Bar

# The user's domain function — clean, typed, testable
async def user_function(foo: Foo, bar: Bar) -> dict:
    return {"baz": foo.process(bar)}

# The adapter — explicit protocol mapping
async def my_actor(state: dict) -> dict:
    foo = Foo(**state["foo"])
    bar = Bar(**state["bar"])
    state["result"] = await user_function(foo, bar)
    return state
```

Users deploy `my_actor` as the handler. The adapter is plain Python — no
framework magic, no env vars, full control over extraction and merging.

## For Generator Handlers (ABI)

```python
async def llm_adapter(state: dict):
    yield "FLY", {"type": "status", "text": "thinking..."}

    response = await call_llm(state["query"], state.get("events", []))

    state.setdefault("events", []).append({
        "type": "model_response",
        "content": response.content,
        "tool_calls": response.tool_calls,
    })
    yield state
```

## Documentation Task

Create `docs/tutorials/adapter-pattern.md` covering:
- Why explicit adapters (vs framework magic)
- Function adapter (simple extraction + merge)
- Generator adapter (streaming + ABI + single yield)
- Class-based handlers with adapters (model loading)
- Testing adapters locally (plain pytest, no runtime needed)
