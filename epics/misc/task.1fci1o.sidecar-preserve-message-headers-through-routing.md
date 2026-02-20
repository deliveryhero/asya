---
title: "Sidecar: preserve message headers through routing"
status: open
priority: 1 # high
type: task
tags:
  - type:feature
---



## Summary

CRITICAL BLOCKER for fan-in, A/B routing, and all header-based features. Currently, headers set by runtime handlers are completely dropped during routing.

## Problem

Two gaps prevent headers from surviving the routing pipeline:

1. **`RuntimeResponse` has no `Headers` field** (`src/asya-sidecar/internal/runtime/client.go`):
   ```go
   type RuntimeResponse struct {
       Type    string           // present
       Payload json.RawMessage  // present
       Route   messages.Route   // present
       Status  *messages.Status // present
       Error   string           // present
       Details ErrorDetails     // present
       // Headers: MISSING
   }
   ```

2. **`routeResponse()` constructs Message without Headers** (`router.go:770-777`):
   ```go
   newMsg := messages.Message{
       ID:       id,
       ParentID: parentID,
       Route:    route,
       Payload:  resp.Payload,
       Status:   outStatus,
       // Headers: NOT SET
   }
   ```

## Changes

### `src/asya-sidecar/internal/runtime/client.go`
- Add `Headers map[string]json.RawMessage` (or `map[string]interface{}`) field to `RuntimeResponse` struct

### `src/asya-sidecar/internal/router/router.go`
- `routeResponse()`: Propagate headers from runtime response (or from original message if runtime did not modify them) to outgoing message
- `handleSuccessResponse()`: Same header propagation for fan-out children
- `sendToSinkQueue()`: Preserve headers when routing to x-sink

### `src/asya-sidecar/pkg/messages/message.go`
- Verify `Message` struct already has `Headers` field (it should)
- If not, add `Headers map[string]json.RawMessage` field

### Tests
- Unit test: Headers from runtime response are preserved in outgoing message
- Unit test: Headers from original message are preserved when runtime does not set headers
- Unit test: Headers survive through fan-out (index 0 and index > 0)
- Unit test: x-asya-route-override header in runtime response is picked up by sidecar

## Why P1

Without this, NO header-based feature works:
- `x-asya-route-override` (A/B routing, fan-in shard resolution)
- `x-asya-fan-in` (fan-in coordination)
- Any future custom headers set by envelope-mode handlers

## References
- RFC: docs/rfc/fan-in/rfc-fan-in.md (entire protocol depends on headers)
- RFC: docs/rfc/rfc-actor-states.md (Key Observations)


---
_Migrated from beads `asya-nduw`_
