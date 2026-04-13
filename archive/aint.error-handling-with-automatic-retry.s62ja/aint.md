---
title: Error Handling with Automatic Retry
status: merged
priority: 2
children:
  - 1f1gq
  - 1f4zi
  - 1f6fd
  - 1feq9
  - 1fezq
  - 1ffmx
  - 1fj66
  - 1fooo
  - 1fsyl
  - 1fu2k
  - 1fzum
---

Implement native automatic error recovery for Asya. RFC: .worktrees/rfc0/docs/rfc/error-handing/rfc-error-handing.md

Key decisions:
- Retry logic in sidecar (no separate _error actor) using SendWithDelay
- _sink replaces happy-end + error-end (single terminal queue)
- _dlq standalone Go worker for infrastructure failures
- Dapr-inspired resiliency config (ASYA_RESILIENCY_* env vars)
- Message schema: status top-level field with lifecycle phases
- Runtime: fully qualified error type + MRO for polymorphic matching
- Transport: SendWithDelay() + Requeue() (replaces Nack())

Subtasks are individual PRs ordered by dependency.
