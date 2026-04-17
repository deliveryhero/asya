---
title: "PR2: MCP adapter + A2A adapter"
status: merged
priority: 1 # high
tags:
  - gateway-rearchitect
dependencies:
  - 9bb3j
---


MCP Streamable HTTP adapter (mark3labs/mcp-go) and A2A JSON-RPC adapter
(a2aproject/a2a-go v2). Single PR — both are small (~800-1300 LOC combined),
share watcher code, and would conflict if merged separately.

Depends on: PR1 (mesh-api core must exist).
Can be parallelized with PR3 (sidecar changes).

See plan.md for detailed execution plan.
