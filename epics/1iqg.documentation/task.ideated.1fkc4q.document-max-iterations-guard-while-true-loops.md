---
title: Document max_iterations guard for while-True loops
priority: 3 # low
type: task
---



Document the max_iterations guard feature added in asya-mhuz (PR #176).

This feature can be surprising/dangerous if users don't know about it:
- while-True loops silently get a RuntimeError guard at 25 iterations (default)
- The error routes the message to error-end, which may look like a bug
- Users need to know how to configure the limit (compile-time and deploy-time)

Documentation should cover:
1. What the guard does and WHY it exists
2. How to configure at compile time: --max-iterations flag
3. How to override at deploy time: ASYA_MAX_LOOP_ITERATIONS env var
4. That while-condition loops are NOT guarded (user controls termination)
5. The payload key (__loop_N_iter) that gets injected - users should be aware
6. Best practices: when to use while-True vs while-condition in agentic flows

Depends on the agentic documentation epic having a place to put this.


---
_Migrated from beads `asya-zqde`_
