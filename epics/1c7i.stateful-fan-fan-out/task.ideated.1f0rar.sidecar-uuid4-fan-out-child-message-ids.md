---
title: "Sidecar: uuid4() for fan-out child message IDs"
priority: 2 # medium
type: task
tags:
  - type:feature
---




## Summary

Replace `fmt.Sprintf("%s-%d", msg.ID, index)` with `uuid.New().String()` in `handleSuccessResponse()` (router.go:580) for fan-out child IDs (index > 0).

## Problem

The current `{id}-{index}` format has a collision bug in pipelines with multiple fan-out actors. Since index 0 keeps the original `message.id`, a message passing through two separate fan-out actors produces duplicate child IDs:

```
Actor A fans out 3:  msg, msg-1, msg-2
Actor C fans out 2:  msg, msg-1   <-- COLLISION
```

## Changes

### `src/asya-sidecar/internal/router/router.go`
- `handleSuccessResponse()` (~line 580): Replace `fmt.Sprintf("%s-%d", msg.ID, index)` with `uuid.New().String()` for index > 0
- Index 0 continues to keep the original `message.id` (unchanged)

### Tests
- `src/asya-sidecar/internal/router/router_test.go`: Update fan-out tests to verify UUID format instead of `{id}-{index}` format
- Add test: Two sequential fan-out actors do not produce colliding IDs
- Verify `parent_id` is still set correctly on index > 0 messages

## References
- Fan-in RFC: `.aint/epics/1c7i.stateful-fan-fan-out/rfc.md` (Yield Order and ID Assignment)


---
_Migrated from beads `asya-g69n`_
