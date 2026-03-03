---
title: "Parser: non-call list elements wrongly parsed as fan-out actors"
priority: 2
tags:
  - type:bug
  - component:compiler
  - component:flow-dsl
---

## Problem

The parser treats any list literal assigned to a payload key as an actor call (sepcifically, if inside `[]` then as fanout
operation). This includes lists containing non-actor expressions like method
calls on state:

```python
state["question_duplicate"] = state.get("question", "")  # not an actor!
state["search_queries"] = [state.get("question", "")]
```

Fails with:
```
Fan-out actor call must have exactly one argument
```

The parser calls `_extract_fanout_actor_call` on `state.get("question", "")`,
which is a method call on the payload, not an actor invocation.

## Root cause

The parser cannot distinguish actor calls (bare top-level function calls like
`analyzer(p)`) from method calls on the payload (`state.get("key")`) or other
non-actor expressions. Any `ast.Call` inside a list literal is assumed to be a
fan-out actor call.

## Fix

Before treating a list element as a fan-out actor call, verify it is a **bare
function call** — i.e., the call target is an `ast.Name` (top-level function)
or a simple `ast.Attribute` on a class instance variable (for class method
actors like `model.predict(p)`). Calls where the target is an attribute on the
payload parameter (`state.get(...)`, `state.items()`) should NOT be treated as
actor calls.

Heuristic: if the call target starts with the flow parameter name (e.g.,
`state`), it's a payload operation, not an actor call.

If all list elements are non-actor expressions, treat the entire assignment as a
`Mutation` instead of `FanOutCall`.

## Found in

`examples/flows/agentic/research_and_refine.py` — `state["search_queries"] =
[state.get("question", "")]` failed validation.

## Workaround

Avoid list literals containing method calls on state. Use scalar assignments:
`state["search_query"] = state.get("question", "")`.
