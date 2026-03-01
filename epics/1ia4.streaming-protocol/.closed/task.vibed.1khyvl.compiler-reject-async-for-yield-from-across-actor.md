---
title: "Compiler: improve error messages for async-for / yield-from rejection"
priority: 3 # low
type: task
reason: "Implemented: explicit AsyncFor rejection + improved yield/yield-from error messages with ABI context"
---


The Flow DSL compiler already rejects `async for`, `yield`, and `yield from`
in flow definitions — but the error messages are generic. This task improves
them to explain *why* these constructs are forbidden and what to do instead.

## Current State

The parser already rejects these constructs:
- `yield` / `yield from` → rejected at line 346-347 (`parser.py`): generic
  "'yield' is not supported in flow definitions"
- `async for` → falls through to line 143: generic "Unsupported statement
  type: AsyncFor"

## What to Change

### 1. `async for` — add explicit rejection with explanation

```python
elif isinstance(stmt, ast.AsyncFor):
    raise FlowCompileError(
        f"{self.filename}:{stmt.lineno}: 'async for' is not supported in "
        f"flow definitions. Streaming events are transport-level and cannot "
        f"flow through message queues. Use 'state = await actor(state)' for "
        f"actor calls — streaming happens transparently via the sidecar."
    )
```

### 2. `yield` / `yield from` — improve error message

```python
if isinstance(value, ast.Yield | ast.YieldFrom):
    raise FlowCompileError(
        f"{self.filename}:{stmt.lineno}: 'yield' is not supported in flow "
        f"definitions. Flows use only 'await' for actor calls. Generator "
        f"logic (streaming, ABI) belongs inside actor handlers, not flows."
    )
```

### 3. ADK patterns remain valid inside handlers

The ADK ReAct loop pattern (`async for event in llm_call(state)`) works
**inside a single actor handler** — it never crosses actor boundaries.
The compiler only processes flow definitions, not handler code.

## Scope Note

This task was originally scoped as "reject async-for/yield-from across actor
boundaries." Epic 1l04 (flow-await-only) simplified the design: flows use
**only `await`**. The compiler already rejects these constructs — this task
just improves the error messages to reference the streaming rationale.

## References

- 1ia4 RFC Section 2 (why streaming events can't flow through queues)
- 1l01 ABI protocol (FLY verb for streaming)
- 1l04 epic (flows use only await)
