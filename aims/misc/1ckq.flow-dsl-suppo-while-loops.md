---
title: "Flow DSL: Support while loops (back-edge routers)"
status: open
priority: 1 # high
type: task
---

Extend Flow DSL compiler to support while loops via back-edge router generation.

SCOPE: while loops ONLY. For loops are out of scope (require free local variables — see asya-FORLOOP).

## What Changes

### Parser (parser.py)
- Parse `while True:` and `while condition:` as WhileLoop IR nodes
- Recursively parse loop body (can contain AwaitCall, Condition, Mutation, etc.)
- Handle `break` as conditional Return (exit loop)

### IR (ir.py)
- New node: `WhileLoop(condition, body)` — loop construct with nested operations

### Grouper (grouper.py)
- Loop router generation: condition-check router -> loop body -> loop-back router -> (back to condition)
- For `while True`, condition router optimized away
- Loop body compiled normally (may contain AwaitCalls creating sub-routers)

### CodeGen (codegen.py)
- Generate loop-back router that manipulates route.actors to re-insert loop-start actors
- Generate condition-check router for conditional while loops

## Primary Use Case: ReAct Loop

```python
async def agent(state: dict) -> AsyncGenerator[dict, None]:
    while True:
        state = await llm_call(state)
        if state.get("tool_calls"):
            state = await execute_tool(state)
        else:
            yield {"type": "result", **state}
            return
```

Compiled to: llm-call -> dispatch-router -> [tool] -> collect-router -> (loop back to llm-call)

## Why while-only
- while loops use only the payload variable (state) — no free local variables needed
- for loops require an iterator variable (e.g., `for tc in tool_calls`) which crosses await boundaries
- for loop support deferred until local variable serialization is implemented

## References
- RFC: docs/rfc/agentic-compiler/agentic-compiler-rfc.md Section 5.3


---
**Close reason**: Merged PR #163: while loop support in Flow DSL compiler


---
_Migrated from beads `asya-bp6`_
