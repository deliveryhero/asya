---
title: "Fix revive lint issues in legacy gateway packages"
status: open
priority: 3
tags: [gateway-rearchitect, cleanup]
---

Pre-existing revive findings suppressed in .golangci.yml:

- internal/a2a/auth.go: A2AAuthMiddleware stutters (rename to AuthMiddleware)
- internal/a2a/executor.go: NewExecutor, Execute, Cancel missing doc comments
- internal/queue/queue.go: QueueMessage stutters (rename to Message)
- pkg/types/envelope.go, message.go: exported consts missing doc comments

**Fix:** Add doc comments, rename stuttering types. Do after adapter migration
to avoid breaking old code.
