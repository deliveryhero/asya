---
title: "debt: mesh-api missing progress_percent in status events"
status: open
priority: 3
tags: [gateway-rearchitect, debt]
---

The old gateway computed `progress_percent` from the route position:
`(len(prev) + weight) / total_hops * 100`. The new mesh-api just stores
whatever the sidecar sends in `HandleEventsPost` — the sidecar's
`ProgressUpdate` struct has no `progress_percent` field.

Tests affected: `test_multihop_chain`, `test_multihop_progress_percentage`.

**Fix options:**
1. Compute in the sidecar: sidecar knows `route.prev` length and can
   estimate progress if total hops are passed in headers.
2. Compute in `HandleEventsPost`: parse `route.prev` and `route.next` from
   the event body and stamp `progress_percent` based on hop count.

Option 2 is cleaner — no sidecar changes needed.

```go
// In HandleEventsPost, if event.Type == "status":
if len(event.Prev)+len(event.Next) > 0 {
    total := len(event.Prev) + 1 + len(event.Next)
    progress := float64(len(event.Prev)+1) / float64(total) * 100
    event.Data = mergeProgress(event.Data, progress)
}
```
