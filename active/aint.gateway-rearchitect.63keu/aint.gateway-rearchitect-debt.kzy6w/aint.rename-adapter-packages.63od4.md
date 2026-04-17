---
title: "Rename mcpadapter→mcp, a2aadapter→a2a after old gateway removal"
status: open
priority: 3
tags: [gateway-rearchitect, cleanup]
---

internal/mcpadapter and internal/a2aadapter use suffixed names to avoid
collision with existing internal/mcp and internal/a2a packages. Once the old
monolith gateway binary (cmd/gateway) is deleted, rename to just internal/mcp
and internal/a2a.

**Blocked on:** removal of cmd/gateway and its imports of old internal/mcp
and internal/a2a packages.
