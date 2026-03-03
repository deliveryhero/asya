---
title: "Layer 2: Python router actor for weighted/probabilistic traffic splitting"
priority: 3 # low
type: task
---

Implement a Python router actor that reads traffic-split config and stamps x-asya-route-override headers dynamically. Supports percentage-based splits (e.g. 90/10 canary). Uses the Flow DSL conditional router pattern. Depends on Layer 1 (x-asya-route-override) which is already merged.
