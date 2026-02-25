---
title: "Gateway: stamp status.deadline_at in message protocol"
priority: 2 # medium
type: task
tags:
  - worktree:.worktrees/1crv/1kz8ww.gateway-stamp-status-deadline-at-message-protocol
  - branch:1crv/1kz8ww.gateway-stamp-status-deadline-at-message-protocol
dependencies:
  - 1crv/1kjf7f
---



## Scope

Fix protocol mismatch: the gateway currently stamps deadline as a top-level `Deadline` field on `ActorMessage`. Change it to stamp `status.deadline_at` inside the message status struct, matching the sidecar protocol.

## Details

### Current state (WORKING but wrong location)
- `src/asya-gateway/internal/queue/queue.go`: `ActorMessage` has `Deadline string` (top-level)
- `NewActorMessage` stamps from `task.Deadline` into `msg.Deadline`
- Backstop timer in taskstore already works correctly
- `TimeoutSec` and `Deadline` on Task type already defined and computed

### Required changes
- Move deadline from `ActorMessage.Deadline` (top-level) into `ActorMessage.Status.DeadlineAt`
- Ensure the field name matches sidecar expectation: `deadline_at` in JSON
- Add `ASYA_GATEWAY_DEFAULT_TIMEOUT` env var (default 5m) for when tool config omits `timeout_seconds`
- If `timeout_seconds=0`, no deadline is stamped (explicit opt-out)

### Unit tests
- Message includes `status.deadline_at` when TimeoutSec > 0
- Message omits `status.deadline_at` when TimeoutSec = 0
- Default timeout applied when tool config omits it
- `deadline_at` is RFC3339 UTC

## Files
- `src/asya-gateway/internal/queue/queue.go`
- `src/asya-gateway/internal/queue/rabbitmq.go`
- `src/asya-gateway/internal/queue/sqs.go`
- `src/asya-gateway/cmd/gateway/main.go` (env var)

## Dependencies
- Depends on 1crv/1kjf7f (status.deadline_at field definition agreement)
- Can be done in parallel with Wave 2 sidecar work

## Wave
Wave 3: Gateway Deadline Alignment
