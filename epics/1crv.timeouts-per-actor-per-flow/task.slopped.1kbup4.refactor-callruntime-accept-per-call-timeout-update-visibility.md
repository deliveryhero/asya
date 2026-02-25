---
title: Refactor CallRuntime to accept per-call timeout and update visibility timeout formula
priority: 2 # medium
type: task
tags:
  - pr:212
dependencies:
  - 1crv/1kjf7f
---


## Scope

Change `CallRuntime` in `src/asya-sidecar/internal/runtime/client.go` to accept timeout as a parameter instead of using the struct field. Update visibility timeout formula in `cmd/sidecar/main.go`.

## Details

### Runtime client refactor
- Change signature: `CallRuntime(ctx, data, timeout, onUpstream)` — add `timeout time.Duration` parameter
- Use passed timeout instead of `c.timeout` struct field for `context.WithTimeout`
- Update all callers in `router/router.go` (2 call sites) to pass `r.cfg.Timeout`
- Remove `timeout` from `Client` struct (no longer needed as field)

### Visibility timeout update
- Current: `cfg.Timeout.Seconds() * 2`
- New: `max(actorTimeout, runtimeTimeout) * 2`
- In `cmd/sidecar/main.go` lines 146-149

### Unit tests
- CallRuntime respects passed timeout parameter
- Visibility timeout: various actorTimeout/runtimeTimeout combinations

## Files
- `src/asya-sidecar/internal/runtime/client.go`
- `src/asya-sidecar/internal/router/router.go` (caller updates)
- `src/asya-sidecar/cmd/sidecar/main.go` (visibility timeout)

## Dependencies
- Depends on 1crv/1kjf7f (DeadlineAt field needed for later per-message timeout)

## Wave
Wave 1: Sidecar Foundation
