---
title: "Escalation action for actor-driven loop termination"
priority: 3 # low
tags:
  - type:feature
---

Support ADK-style escalation where an actor (tool) can signal loop termination
from inside the loop body, without the flow needing to check a specific payload
field.

## ADK Pattern

In ADK, a LoopAgent iterates sub-agents until one sets `escalate = True`:

```python
# ADK: tool signals loop exit
def approve(tool_context: ToolContext):
    tool_context.actions.escalate = True
    return "Approved"

# LoopAgent checks every event:
async for event in sub_agent.run_async(ctx):
    yield event
    if event.actions.escalate:
        should_exit = True
```

See survey-adk-data-flow.md Section 5.4 for full LoopAgent mechanics.

## Current Asya Approach

Asya's flow DSL while-loop uses payload-based conditions:

```python
async def review_loop(state: dict) -> dict:
    while not state.get("approved"):
        state = await writer(state)
        state = await critic(state)   # critic sets state["approved"] = True
    return state
```

This works but requires the flow author to:
1. Know which payload field the actor will set
2. Explicitly check that field in the while condition

## Proposed Solution

### Convention-based escalation via payload

Define a reserved payload field `_escalate` that the loop condition router
checks automatically:

1. Actor handler sets `state["_escalate"] = True` (or writes to VFS)
2. While-loop condition router checks `p.get("_escalate")` in addition to
   the user-defined condition
3. After loop exits, cleanup: `p.pop("_escalate", None)`

### Flow DSL syntax

No syntax change needed. The while-loop condition already supports payload checks.
The convention is purely at the handler level -- actors that want to break a loop
set `state["_escalate"] = True`.

### Alternative: VFS-based escalation

Actor writes to `/proc/asya/msg/headers/escalate`:
```python
with open("/proc/asya/msg/headers/escalate", "w") as f:
    f.write("true")
```

The sidecar reads this header and includes it in the routed message. The
condition router checks `message["headers"].get("escalate")`.

## Impact Assessment

This is a **convention**, not a framework feature. The current while-loop
infrastructure already supports this pattern via payload fields. The value
of this task is:
- Documenting the convention
- Optionally: compiler sugar for `while not escalated:` that generates the check
- Optionally: adding `_escalate` to the reserved payload field namespace

## References

- survey-adk-data-flow.md Section 5.4 (LoopAgent), Section 8.2 (Gap 4)
- 1irj RFC Section 3 (while-loop infrastructure)
- epic 1ixt (message metadata VFS -- headers)
