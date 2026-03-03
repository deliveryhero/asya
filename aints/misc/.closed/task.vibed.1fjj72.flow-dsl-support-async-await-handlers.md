---
title: "Flow DSL: Support async/await handlers"
priority: 1 # high
type: task
tags:
  - type:feature
---






Extend Flow DSL compiler to support async/await syntax with CPS (Continuation-Passing Style) transformation.

## What Changes

### Parser (parser.py)
- Accept `async def flow_name(state: dict) -> dict` and `async def flow_name(state: dict) -> AsyncGenerator[dict, None]`
- Accept parameter names: `state`, `s`, `p`, `payload`
- Parse `state = await actor(state)` as AwaitCall IR node
- Parse `yield expr` as YieldEvent IR node

### IR (ir.py)
- New node: `AwaitCall(name, assign_to)` -- CPS split point
- New node: `YieldEvent(code, is_final)` -- streaming/control event
- New node: `AsyncFlowFunction(is_generator)` -- marks async flow

### Grouper (grouper.py)  
- CPS transformation: each AwaitCall terminates current router, creates actor reference, generates continuation router
- Yield handling: intermediate yields = streaming, final yield = control event

### CodeGen (codegen.py)
- Generate continuation router code that receives actor results and continues flow
- Handle assign_to variable as local alias for payload

## Test Cases (from real ADK examples)

### Sequential async:
```python
async def llm_auditor(state: dict) -> dict:
    state = await critic(state)
    state = await reviser(state)
    return state
```

### Conditional async:
```python
async def pipeline(state: dict) -> dict:
    state = await classifier(state)
    if state["type"] == "text":
        state = await text_proc(state)
    else:
        state = await image_proc(state)
    return state
```

## References
- RFC: docs/rfc/agentic-compiler/agentic-compiler-rfc.md (Sections 3-6)
- ADK LLM Auditor: validated reference example


---
_Migrated from beads `asya-pec`_
