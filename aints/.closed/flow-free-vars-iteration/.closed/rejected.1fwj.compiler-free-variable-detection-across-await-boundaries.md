---
title: "Compiler: free variable detection across await boundaries"
priority: 1 # high
tags:
  - type:feature
reason: All state lives in p dict by design. Parser already prevents local variable assignments — free variables cannot exist by construction.
---






Add static analysis to detect local variables that cross await boundaries and emit compiler errors.

## Problem
After CPS transformation, a local variable assigned before an await and referenced after it will be lost because the entry router and continuation router are separate actors on potentially different pods.

Example:
  var1 = compute()              # assigned before await
  state = await actor_a(state)  # await boundary
  print(var1)                   # used after await -- ERROR!

## Solution (Phase 1: Error)
- After parsing, analyze variable liveness across AwaitCall boundaries
- If a variable is assigned before an await and referenced after it, emit FlowCompileError
- Message: "Local variable 'var1' crosses await boundary at line N. Move it into state dict: state['var1'] = compute()"

## Solution (Phase 2: Auto-serialize, future)
- Automatically insert state["__var1"] = var1 before await
- Automatically insert var1 = state.pop("__var1") after await
- Requires careful analysis of all variable references

## Primary Motivating Use Case: ADK ReAct Loop

This is the critical blocker for `react_*` flow compilation (task 1k38vs).
The ADK ReAct loop pattern compiles cleanly (while-true, conditionals, await,
break) but any local variable across an await boundary is silently lost:

```python
async def react_agent(state: dict) -> dict:
    while True:
        state = await llm_call(state)
        # This is safe -- reads from state (payload):
        if state.get("tool_calls"):
            state = await tool_executor(state)
        else:
            break
    return state
```

The above works because `tool_calls` is read from the payload. But real-world
patterns often extract locals:

```python
async def react_with_locals(state: dict) -> dict:
    original_query = state["query"]       # local variable
    while True:
        state = await llm_call(state)
        if state.get("done"):
            break
        state["context"] = original_query  # LOST after first await!
        state = await tool_executor(state)
    return state
```

See survey-adk-data-flow.md Section 8.2 (Gap 1) for full ADK mapping analysis.

## References

- RFC Section 2.3 (Free Variables)
- survey-adk-data-flow.md (ADK data flow patterns and Asya gap analysis)
- task 1k38vs (enable react_* flow compilation -- blocked on this)


---
_Migrated from beads `asya-cv4g`_
