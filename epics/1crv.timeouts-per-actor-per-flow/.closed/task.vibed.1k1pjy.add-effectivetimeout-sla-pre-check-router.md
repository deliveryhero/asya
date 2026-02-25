---
title: Add effectiveTimeout and SLA pre-check to router
priority: 2 # medium
type: task
tags:
  - worktree:.worktrees/1crv/1k1pjy.add-effectivetimeout-sla-pre-check-router
  - branch:1crv/1k1pjy.add-effectivetimeout-sla-pre-check-router
  - pr:214
dependencies:
  - 1crv/1kjf7f
  - 1crv/1kbup4
---




## Scope

Wire up `ASYA_RESILIENCY_ACTOR_TIMEOUT` (currently parsed but unused) and add SLA deadline enforcement in the router before calling the runtime.

## Details

### effectiveTimeout method
```go
func (r *Router) effectiveTimeout(msg *messages.Message) time.Duration
```
- Start with `r.cfg.Timeout` (ASYA_RUNTIME_TIMEOUT, 5m default)
- If `r.cfg.Resiliency.ActorTimeout > 0`, use it (lower wins)
- If `msg.ParseDeadline()` returns a valid deadline, use `time.Until(deadline)` (lower wins)
- Return the effective timeout

### SLA pre-check
Before calling `CallRuntime`, check if message is expired:
- Parse `status.deadline_at`
- If `now > deadline_at`: report timeout to gateway, route to x-sink with `status.phase=failed, status.reason=Timeout`, ack message, return (no retry)
- If not expired: call `CallRuntime` with effective timeout

### Expired message flow
1. Report status to gateway: `{status: "failed", reason: "Timeout"}`
2. Route message to x-sink with timeout status
3. Ack message from queue
4. No retry — SLA expiry is terminal

### Unit tests
- effectiveTimeout: all precedence combinations (runtime only, actor < runtime, SLA < actor, no deadline, etc.)
- SLA pre-check: expired message skips runtime, routes to x-sink
- SLA pre-check: valid message calls runtime with effective timeout

## Files
- `src/asya-sidecar/internal/router/router.go`
- `src/asya-sidecar/internal/router/router_test.go`

## Dependencies
- Depends on 1crv/1kjf7f (DeadlineAt field + ParseDeadline helper)
- Depends on 1crv/1kbup4 (per-call timeout in CallRuntime)

## Wave
Wave 2: Sidecar SLA Enforcement
