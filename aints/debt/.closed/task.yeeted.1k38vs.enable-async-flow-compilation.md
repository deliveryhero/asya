---
title: Enable flow compilation for async actors
priority: 2 # medium
type: task
dependencies:
  - 1irj/1fwjb3
---


Enable `react_*` and `fanout_*` flow compilation in `.pre-commit-hooks/compile-flows.sh`.

## Currently Muted

```sh
# .pre-commit-hooks/compile-flows.sh
    # TODO: uncomment react_ once asya-cx34 is done
    [[ "$flow_name" == react_* ]] && continue
    # TODO: uncomment fanout_ once fan-out codegen is done (1fr7i0)
    [[ "$flow_name" == fanout_* ]] && continue
```

## What's Actually Blocking

### `react_*` flows

The `react_*` flows use the ADK-style ReAct loop pattern:

```python
async def react_loop(state: dict) -> dict:
    while True:
        state = await llm_call(state)
        if state.get("tool_calls"):
            state = await tool_executor(state)
        else:
            break
    return state
```

This pattern is **structurally supported** by the flow compiler (while-loop,
conditionals, await calls, break). The blocker is **free variable serialization**
(epic 1irj): if any local variable is assigned before an `await` and referenced
after it, it's lost at the actor boundary. The `react_*` fixtures likely have
such variables.

The blocker is NOT async generator support -- streaming is handled transparently
by the sidecar (upstream events go to gateway via HTTP, downstream via queue).

### `fanout_*` flows

Fan-out codegen is done (epic 1c7i, vibed). These should be re-tested and
unblocked. The `fanout_*` skip may be stale.

## Action Items

1. Attempt to compile each `react_*` flow -- capture the actual error
2. If errors are free variable issues: blocked on 1irj/1fwjb3
3. If errors are something else: fix and enable
4. Re-test `fanout_*` flows -- likely unblockable now
5. Remove the `continue` lines from compile-flows.sh once compilation succeeds
