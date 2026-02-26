---
title: "Compiler: eliminate no-op break-check routers in while-loop bodies"
priority: 3 # low
type: task
---

## Context

The grouper emits a dedicated conditional router for `if cond: break` inside while-loop bodies. Example from `complex_combined.py` line 25:

```python
while p["i"] < p["max_iterations"]:
    ...
    p = handler_process(p)
    if p["stop_early"]:
        break
```

This produces `router_complex_combined_flow_line_25_if`:

```python
if p['stop_early']:
    _next.append(resolve("handler_finalize"))  # break target
else:
    pass  # no-op: loop_back is already in _next_tail
```

The false branch is a no-op — `loop_back` is already queued in `_next_tail` by the parent while router. This means every non-breaking iteration pays an extra queue hop and actor invocation just to evaluate a condition and do nothing.

## Proposed optimization

Fold the break condition into the preceding router (or the while condition router) so there is no standalone no-op router. Two approaches:

1. **Merge into preceding seq/mutation router**: The `line_20_if` router already runs before `handler_process`. After `handler_process`, the break-check could be appended to the route inline — e.g., the while router emits `[..., handler_process, loop_back]` but with a conditional that short-circuits to the break target when `stop_early` is true.

2. **Merge into loop_back router**: `loop_back` currently just re-inserts the while condition. It could first check the break condition before re-inserting.

3. **Grouper-level elimination**: Detect `if COND: break` as the last statement in a while body and fold it into the while condition or loop_back router during grouping, rather than emitting a separate router.

## Affected patterns

- `if cond: break` (last statement in while body) — `complex_combined`, `while_with_break`
- `if cond: continue` may have a similar pattern but is less wasteful since the continue path also does work (skip to loop_back)

## Notes

- This is a runtime performance optimization — the current code is functionally correct
- Each eliminated no-op router saves one queue send + receive + actor invocation per loop iteration
- The DOT visualization would also become cleaner (fewer nodes)
