---
title: "Consider moving sseclient to pkg/ for cross-module reuse"
status: open
priority: 3
tags: [gateway-rearchitect, cleanup]
---

internal/sseclient/ is a generic SSE line-protocol parser with no
gateway-specific dependencies. If the adapters ever become separate Go
modules (separate repos), this would need to move to pkg/.

**Not blocking** — only relevant if Go modules are split. Currently all
adapters are in the same module (asya-gateway).
