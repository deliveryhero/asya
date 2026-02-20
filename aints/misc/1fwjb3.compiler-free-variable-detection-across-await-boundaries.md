---
title: "Compiler: free variable detection across await boundaries"
status: open
priority: 3 # low
type: task
tags:
  - type:feature
dependencies:
  - misc/1fkrbh
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

## References
- RFC Section 2.3 (Free Variables)


---
_Migrated from beads `asya-cv4g`_
