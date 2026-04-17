---
title: "Rename mcpadapter→mcp, a2aadapter→a2a after old gateway removal"
status: open
priority: 3
tags: [gateway-rearchitect, cleanup]
---

**Source:** Structural review of PR2 ([#444](https://github.com/deliveryhero/asya/pull/444)).

**Problem:** `internal/mcpadapter` and `internal/a2aadapter` use suffixed names
to avoid Go package collision with existing `internal/mcp` and `internal/a2a`.
Both old and new packages coexist because `cmd/gateway/main.go` still imports
the old packages.

**Blocked on:** Deletion of `cmd/gateway/` and its imports of `internal/mcp/`
and `internal/a2a/`. This happens when the old monolith gateway is fully
replaced by mesh-api + adapters.

**Fix:** After removing `cmd/gateway/`, `internal/mcp/`, `internal/a2a/`:
1. `git mv internal/mcpadapter internal/mcp`
2. `git mv internal/a2aadapter internal/a2a`
3. Update all imports in `cmd/mcp-adapter/` and `cmd/a2a-adapter/`

**Files:**
- `src/asya-gateway/internal/mcpadapter/` → `internal/mcp/`
- `src/asya-gateway/internal/a2aadapter/` → `internal/a2a/`
- `src/asya-gateway/cmd/mcp-adapter/main.go` — import paths
- `src/asya-gateway/cmd/a2a-adapter/main.go` — import paths
