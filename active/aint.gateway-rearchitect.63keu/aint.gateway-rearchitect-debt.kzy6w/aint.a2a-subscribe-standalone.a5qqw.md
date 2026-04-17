---
title: "A2A tasks/subscribe for in-flight tasks"
status: open
priority: 2
tags: [gateway-rearchitect, a2a]
---

**Source:** RFC conformance review of PR2 ([#444](https://github.com/deliveryhero/asya/pull/444)).

**Problem:** A2A `tasks/subscribe` on an already-running task returns a snapshot,
not a live SSE stream. `StoreAdapter.Get` (`internal/a2aadapter/store.go:33`)
fetches current state from mesh-api but doesn't set up SSE event forwarding.

The a2a-go library calls `Executor.Execute` for `tasks/sendSubscribe` (create +
stream) but for standalone `tasks/subscribe` it relies on `TaskStore.Get` which
only returns a point-in-time snapshot.

**Expected (RFC 4.3):** `tasks/subscribe` should open an SSE connection to
`GET /api/v1/mesh/{id}/events` and relay events as A2A `TaskStatusUpdateEvent`
and `TaskArtifactUpdateEvent`, same as the live path in `executor.go:104-152`.

**Fix:** Either:
1. Add a `Subscribe` method to `StoreAdapter` that opens SSE, or
2. Move the SSE relay logic from `Executor.Execute` into a shared function
   that both `Execute` and a new subscribe handler can call.

**Files:**
- `src/asya-gateway/internal/a2aadapter/store.go` — StoreAdapter.Get
- `src/asya-gateway/internal/a2aadapter/executor.go` — SSE relay logic (lines 104-152)
