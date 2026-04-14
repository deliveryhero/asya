---
title: "Post-compilation invariant checks: all routers visible in DOT with proper connectivity"
status: open
priority: 2
---

## Context

After fixing the while-loop DOT visualization dead-end bug (#226), we have strong graph invariants in `test_dotgen_invariant.py` (all nodes reachable from entrypoint, all nodes can reach exitpoint). However, we lack a check that **every router function generated in `routers.py` is actually represented in the DOT graph** and has proper connectivity.

## Requirements

Add post-compilation checks (run after every `asya flow compile`) that verify:

1. **Router-DOT parity**: Every router function defined in `routers.py` (except `resolve()` and module-level code) must have a corresponding node in `flow.dot` (similarly, to the future React-flow components as alternative to dot).
2. **Input/output connectivity**: Every node in the DOT graph must have:
   - At least one **incoming** edge (except `start_*`)
   - At least one **outgoing** edge (except `end_*`)
3. **No orphan nodes**: No node should be disconnected (0 in + 0 out)

## Notes

- These checks should run as unit tests (parameterized over all compiled example flows), similar to `test_dotgen_invariant.py`
- The existing invariant tests check reachability via BFS; the new checks are complementary (structural vs graph-theoretic)
- Also observed: `router_complex_combined_flow_line_25_if` is a no-op hop router for the `if stop_early: break` pattern. The grouper could potentially fold this into the preceding router. That optimization is a separate concern (compiler/grouper) but is related to the "why do we have routers that don't do useful work" question
