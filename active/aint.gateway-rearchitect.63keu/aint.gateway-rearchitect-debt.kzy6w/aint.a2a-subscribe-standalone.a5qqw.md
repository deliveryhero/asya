---
title: "A2A tasks/subscribe for in-flight tasks"
status: open
priority: 2
tags: [gateway-rearchitect, a2a]
---

StoreAdapter.Get returns current state but doesn't set up live SSE streaming
for an already-running task. A client calling tasks/subscribe on an in-flight
task gets a snapshot, not live events.

**Fix:** Subscribe to mesh-api SSE from StoreAdapter or Executor when the
task is non-terminal. Requires wiring the SSE subscription into the a2a-go
library's streaming response path.
