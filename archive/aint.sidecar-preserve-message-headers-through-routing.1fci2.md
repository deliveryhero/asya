---
title: "Sidecar: preserve message headers through routing"
status: merged
priority: 1
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
       Payload json.RawMessage  `json:"payload,omitempty"`  // present
       Route   messages.Route   `json:"route,omitempty"`    // present
       Status  *messages.Status `json:"status,omitempty"`   // present
       Error   string           `json:"error,omitempty"`    // present
       Details ErrorDetails     `json:"details,omitempty"`  // present
       // Headers: MISSING
   }
   ```

2. **`routeResponse()` constructs Message without Headers** (`router.go:771-778`):
   ```go
   newMsg := messages.Message{
       ID:       id,
       ParentID: parentID,
       Route:    route,
       Payload:  payload,
       Status:   outStatus,
       // Headers: NOT SET
   }
   ```

## Changes

### `src/asya-sidecar/internal/runtime/client.go`
- Add `Headers map[string]json.RawMessage` (or `map[string]interface{}`) field to `RuntimeResponse` struct

### `src/asya-sidecar/internal/router/router.go`
- `routeResponse()` (line ~721): Accept headers parameter, set `newMsg.Headers` when constructing the outbound Message
- `handleSuccessResponse()` (line ~558): Pass headers from runtime response (or original message if runtime did not set them) into `routeResponse()`
- `sendToSinkQueue()` (line ~816): Preserve headers when routing to x-sink

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
- `x-asya-fan-in` (fan-in coordination — all flavors depend on this header)
- `x-asya-route-override` (A/B routing, fan-in shard resolution for sharded flavors)
- Any future custom headers set by envelope-mode handlers

## References
- Fan-in RFC: `.aint/epics/1c7i.stateful-fan-fan-out/rfc.md` (entire protocol depends on headers)


_Migrated from beads `asya-nduw`_
