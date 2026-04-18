---
title: "debt: mesh-api missing SLA backstop timer (deadline reaper)"
status: open
priority: 2
tags: [gateway-rearchitect, debt]
---

The old gateway had a `handleTimeout()` goroutine that scanned for tasks
with expired `deadline_at` and marked them `failed`. The new mesh-api
stores `deadline_at` in the DB (via `MessageStore`) but has no reaper.

Tests affected: `test_sla_e2e::test_gateway_backstop_race`,
`test_sla_e2e::test_slow_actor_exceeds_sla`.

**Fix:**
Add a background ticker in `mesh-api/main.go` that calls `FindExpired()`
(already in the `MessageStore` interface spec) every N seconds and marks
those tasks as `failed` with reason "task timed out".

```go
// In main.go, after server startup:
go func() {
    ticker := time.NewTicker(5 * time.Second)
    defer ticker.Stop()
    for {
        select {
        case <-ctx.Done():
            return
        case <-ticker.C:
            ids, _ := msgStore.FindExpired(context.Background())
            for _, id := range ids {
                _ = msgStore.UpdateStatus(ctx, id, types.MessageStatusFailed,
                    json.RawMessage(`{"error":"task timed out"}`))
            }
        }
    }
}()
```

Also needs `FindExpired() ([]string, error)` on `MessageStore` interface
and implementation in `StateProxyStore` that queries:
`WHERE value->>'status' NOT IN ('succeeded','failed','canceled')
 AND value->>'deadline_at' < now()`.
