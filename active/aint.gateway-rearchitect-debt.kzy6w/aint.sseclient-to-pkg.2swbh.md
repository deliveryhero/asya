---
title: "Consider moving sseclient to pkg/ for cross-module reuse"
status: open
priority: 3
tags: [gateway-rearchitect, cleanup]
---

**Source:** Structural review of PR2 ([#444](https://github.com/deliveryhero/asya/pull/444)).

**Problem:** `internal/sseclient/` is a generic SSE line-protocol parser with
no gateway-specific dependencies. It only imports stdlib (`bufio`, `context`,
`encoding/json`, `fmt`, `io`, `net/http`, `strings`, `time`).

Currently both MCP and A2A adapters import it from `internal/`. If adapters
ever move to separate Go modules, `internal/` packages are not importable
across modules.

**Not blocking** — only relevant if the Go module is split. All three binaries
(mesh-api, mcp-adapter, a2a-adapter) are in the same `asya-gateway` module.

**Fix (if needed):** `git mv internal/sseclient pkg/sseclient`. No code changes
needed — just the import paths in `internal/meshclient/client.go` and test files.
