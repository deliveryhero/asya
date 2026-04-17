---
title: "Extract shared cmdutil from adapter mains"
status: open
priority: 3
tags: [gateway-rearchitect, cleanup]
---

cmd/mcp-adapter/main.go and cmd/a2a-adapter/main.go both define identical
functions: requireEnv, getEnv, parseLogLevel, parseDuration.

**Fix:** Extract to internal/cmdutil/ package. cmd/mesh-api/main.go has
similar functions too.
