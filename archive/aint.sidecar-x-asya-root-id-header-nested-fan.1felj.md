---
title: "Sidecar: x-asya-root-id header for nested fan-out tracing"
status: rejected
priority: 3
tags:
  - type:feature
reason: Decided to go with virtual actors for simplicity
---

## Summary

Add `root_id` tracing for nested fan-outs. When a fan-out child itself fans out, `parent_id` only links to the immediate parent. `root_id` traces back to the ultimate root message.

## Logic

```
root_id = root_id or parent_id
```

- If the message already carries `x-asya-root-id` (from a previous fan-out), preserve it
- If not, derive from `parent_id` (the immediate fan-out parent)
- The root message itself has neither `root_id` nor `parent_id`

## Changes

### `src/asya-sidecar/internal/router/router.go`
- `handleSuccessResponse()`: For index > 0, set `x-asya-root-id` header:
  - If incoming message has `x-asya-root-id` header → preserve it
  - Else → set to `msg.ID` (the original message ID)

### Tests
- Unit test: First fan-out sets `root_id = msg.ID` on children
- Unit test: Nested fan-out preserves existing `root_id`
- Unit test: Root message has no `root_id`

## Dependencies
- DEPENDS ON: Sidecar header preservation (asya-nduw)

## References
- RFC: docs/rfc/rfc-actor-states.md (root_id for Nested Fan-Out Tracing)


---
_Migrated from beads `asya-9n0r`_
