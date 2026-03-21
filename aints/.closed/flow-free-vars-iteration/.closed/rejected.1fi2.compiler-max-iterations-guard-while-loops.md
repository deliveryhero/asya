---
title: "Compiler: max_iterations guard for while loops"
priority: 3 # low
tags:
  - type:feature
---






Add compiler-enforced loop termination to prevent infinite ReAct loops.

## Problem
If the LLM never stops calling tools, the while True loop runs forever, consuming unbounded resources.

## Solution

### Compiler-level
- When compiling while True, inject an iteration counter into the payload
- Generated loop-back router increments counter: state["__loop_N_iter"] += 1
- Generated condition router checks: if state["__loop_N_iter"] >= MAX_ITER: route to error-end
- Default MAX_ITER = 25 (configurable via compiler flag or env var)

### User-level
- Users can specify max iterations in the flow:
  while state.get("__iterations", 0) < 10:  # user-controlled limit
      state = await llm_call(state)
      ...
- For while True, compiler auto-injects the guard

### Deployment-level
- ASYA_MAX_LOOP_ITERATIONS env var on router actors (default: 25)
- Overridable per-flow in CRD annotations

## Test Plan
- Compile while True, verify guard code is injected
- Execute router with iteration count at limit, verify routes to error-end
- Compile while condition, verify no double-guard

## References
- ADK LoopAgent: max_iterations parameter
- RFC Section 14 Open Question 4


---
**Close reason**: Implemented max_iterations guard for while-True loops in the flow compiler


---
_Migrated from beads `asya-mhuz`_
