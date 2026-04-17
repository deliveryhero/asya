---
title: "Fix revive lint issues in legacy gateway packages"
status: open
priority: 3
tags: [gateway-rearchitect, cleanup]
---

**Source:** golangci-lint findings when reviewing PR2 ([#444](https://github.com/deliveryhero/asya/pull/444)).

**Problem:** Pre-existing revive violations in legacy gateway packages. Not
visible before because revive was commented out in the old `.golangci.yml`.

Specific findings:
- `internal/a2a/auth.go:175` — `A2AAuthMiddleware` stutters (→ `AuthMiddleware`)
- `internal/a2a/executor.go:31,45,160` — `NewExecutor`, `Execute`, `Cancel`
  missing exported doc comments
- `internal/queue/queue.go:63` — `QueueMessage` stutters (→ `Message`)
- `pkg/types/envelope.go:12` — exported const block missing doc comment
- `pkg/types/message.go:12` — exported const block missing doc comment
- `internal/queue/pubsub.go:11` — stale `//nolint:staticcheck` directive

**Fix:** Add doc comments, rename stuttering identifiers. Best done after
the adapter migration (aint 63od4) to avoid touching code that will be deleted.
