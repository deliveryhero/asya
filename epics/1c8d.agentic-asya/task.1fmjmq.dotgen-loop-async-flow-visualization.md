---
title: "DotGen: loop and async flow visualization"
status: open
priority: 2 # medium
type: task
tags:
  - type:feature
dependencies:
  - misc/1fkrbh
---





Extend the Graphviz dot generator to visualize async flow constructs: loops, await splits, streaming events.

## Changes

### dotgen.py
- Render loop back-edges as dashed arrows pointing backward
- Render await split points with different node shape (e.g., parallelogram for actors)
- Render streaming yield events with dotted arrows to a "gateway" node
- Add legend for new node/edge types
- Color-code: routers (blue), user actors (green), loop edges (red), streaming (orange)

## Visual Example
The ReAct loop should render as:
- entry-router (blue box) -> llm-call (green box)
- llm-call -> dispatch-router (blue diamond)
- dispatch-router -> google-search (green box) [label: tool_calls]
- dispatch-router -> reviser (green box) [label: no tools]
- google-search -> collect-router (blue box)
- collect-router -> llm-call (red dashed arrow, loop back)

## Test Plan
- Generate dot for react_loop.py, verify edges and node types
- Generate dot for async_sequential.py, verify simple linear graph
- Visual regression: compare PNG output with golden files

## References
- Current dotgen.py: src/asya-cli/asya_cli/flow/dotgen.py (181 lines)


---
_Migrated from beads `asya-asp7`_
