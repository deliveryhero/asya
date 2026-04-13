---
title: Verify fan-out inside while loops works at runtime
status: merged
priority: 3
parent: drsjr
tags:
  - type:testing
  - component:compiler
  - component:flow-dsl
  - pr:246
---

## Problem

Fan-out inside while loops compiles without errors, but the runtime behavior
has not been verified. The interaction between fan-out (which spawns N+1
messages: parent + N slices) and loop-back routers (which re-insert the loop
body into `route.next`) may produce unexpected routing.

Specifically: after fan-in collects all slices, the aggregated message needs
to continue through the rest of the loop body AND potentially loop back.
The routing continuation from fan-in must correctly reference the loop-back
router.

Fanout should be able to happen in any context - if/else branch, while loop, multiple nested if/while, etc.


## Example

```python
async def debate(state: dict) -> dict:
    while True:
        state["positions"] = [
            await debater_a(state),
            await debater_b(state),
            await debater_c(state),
        ]
        state = await convergence_checker(state)
        if state.get("converged"):
            break
```

This compiles but needs a component test to verify:
1. Fan-out correctly dispatches 3 messages inside the loop
2. Fan-in correctly aggregates results
3. The loop-back router correctly re-enters after fan-in
4. Break correctly exits the loop after fan-in

## Acceptance criteria

- Component test in `testing/component/flow-compiler/` that compiles and
  executes a flow with fan-out inside a while loop
- Verify correct message count at each stage
- Verify loop termination works after fan-in

## Found in

`examples/flows/agentic/multi_agent_debate.py` — uses sequential revision as
workaround because fan-out inside while loops is untested.
