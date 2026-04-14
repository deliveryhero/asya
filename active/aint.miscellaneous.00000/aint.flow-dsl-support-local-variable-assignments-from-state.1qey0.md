---
title: "Flow DSL: support local variable assignments from state accessors"
status: open
priority: 3
tags:
  - component:compiler
  - component:flow-dsl
---

## Problem

The parser rejects local variable assignments like:

```python
approval_status = state.get("approval")
if approval_status in ("approved", "modified"):
    ...
```

Error: `Unsupported assignment target. Handler results must be assigned to 'p'`

Currently only `state["key"] = value` and `state = await handler(state)` are
supported as assignment targets.

## Motivation

Local variables are a natural Python pattern for:
- Avoiding repeated `state.get(...)` calls in conditions
- Intermediate computations before writing back to state
- Readability (meaningful variable names instead of long dict accesses)

## Proposed approach

Treat local variable assignments as **router-local temporaries** in the
generated code. The variable lives only within the current router function
and is not persisted to the message payload.

The parser should:
1. Allow `name = expr` where `expr` reads from state (e.g., `state.get(...)`,
   `state["key"]`, `len(state["list"])`)
2. Track local names to avoid confusing them with actor calls
3. Emit the assignment as-is in the generated router code

## Found in

PR #252 review: Gemini suggested combining `if approved / if modified` into
`approval_status = state.get("approval"); if approval_status in (...)` but
this does not compile. Workaround: use `state.get("approval") in (...)` inline.
