---
title: "Extract shared cmdutil from adapter mains"
status: open
priority: 3
tags: [gateway-rearchitect, cleanup]
---

**Source:** Code review of PR2 ([#444](https://github.com/deliveryhero/asya/pull/444)).

**Problem:** `cmd/mcp-adapter/main.go` and `cmd/a2a-adapter/main.go` both
define identical helper functions:
- `requireEnv(key string) string`
- `getEnv(key, fallback string) string`
- `parseLogLevel(s string) slog.Level`
- `parseDuration(s string, fallback time.Duration) time.Duration`

`cmd/mesh-api/main.go` has similar functions (`requireEnv` at line 131).

**Fix:** Create `internal/cmdutil/` package with these shared helpers.
Update all three binaries to import from there.
