---
title: 'Parser: empty list literal state["x"] = [] wrongly parsed as fan-out'
status: merged
priority: 1
tags:
  - type:bug
  - component:compiler
  - component:flow-dsl
---

## Problem

The parser sees `state["x"] = [...]` and checks if the right-hand side is a
list literal. Any list assigned to a payload key triggers the fan-out code path.
An empty list `[]` has no function calls inside, so it fails with:

```
Empty list literal is not valid for fan-out
```

This prevents common initialization patterns like:
```python
state["worker_results"] = []
state["step_results"] = []
state["findings"] = []
```

Additionally, any list definition WITHOUT a function call must also work, for example:

```
state["worker_results"] = [1, 2, 3]
```

## Root cause

`parser.py` method `_parse_assignment` checks `isinstance(value, ast.List)` and
routes to `_parse_fanout_literal` without first checking whether the list
contains any function calls. An empty list (or a list of plain values) is a
payload mutation, not a fan-out.

## Fix

In `_parse_fanout_literal` (or before dispatching to it), check that the list
has at least one element AND that at least one element is an `ast.Call` (or
`ast.Await` wrapping a call). If not, treat the assignment as a regular
`Mutation` operation.

## Found in

`examples/flows/agentic/` — 3 out of 15 agentic pattern examples initially
failed validation due to this: `orchestrator_workers.py`, `plan_and_execute.py`,
`research_and_refine.py`.

## Workaround

Remove explicit empty list initialization. Use `state.get("key", [])` in
downstream handlers instead.
