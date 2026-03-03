---
title: Support async-for fan-in from multi-yield actors
priority: 2 # medium
type: task
reason: async for forbidden in flows — streaming cannot cross actor boundaries. Fan-in from multi-yield actors needs separate design if ever needed.
---


When a single actor yields multiple payloads (non-ABI generator), the flow
should support collecting those results via async-for comprehension syntax:

```python
state["computed"] = [e async for e in multi_actor(state)]
```

This differs from current fan-out (which sends TO multiple actors). Here a
single actor PRODUCES multiple messages, and the flow collects them.

See conversation notes for syntax alternatives and architectural implications.
