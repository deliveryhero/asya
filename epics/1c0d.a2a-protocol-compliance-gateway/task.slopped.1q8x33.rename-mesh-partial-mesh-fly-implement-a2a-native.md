---
title: Rename /mesh/partial to /mesh/fly and implement A2A-native FLY format
priority: 2 # medium
type: task
dependencies: [1c0d/1qdvt8]
---

## Summary

Rename the gateway endpoint from `POST /mesh/{id}/partial` to
`POST /mesh/{id}/fly` and rename the corresponding sidecar URL. Then implement
A2A-native FLY event translation in the gateway so that FLY dicts from actors
are broadcast as properly typed A2A SSE events.

Reference: RFC Section 11.1 (Renamed Sidecar-Facing Routes), Section 9.5.3
(Gateway Partial Event Handling).

## Endpoint Rename

### Gateway

- Rename route: `POST /mesh/{id}/partial` -> `POST /mesh/{id}/fly`
- Rename handler: `HandleMeshPartial` -> `HandleMeshFly`
- Update the mux registration in `cmd/gateway/main.go` (or wherever routes
  are registered) to use the new path

### Sidecar

- Update the URL used by the sidecar's progress reporter when forwarding FLY
  events: change from `/mesh/{id}/partial` to `/mesh/{id}/fly` in
  `internal/progress/reporter.go`
- Ensure backward compatibility is not needed (this is an internal API
  between sidecar and gateway, deployed together)

## A2A-Native FLY Event Translation (RFC Section 9.5.3)

When the gateway receives a FLY dict on `POST /mesh/{id}/fly`, it must
inspect the dict's top-level key to determine the correct A2A SSE event type
before broadcasting to subscribers.

### Event type detection

| FLY Dict Top-Level Key | SSE Event Type | Description |
|------------------------|----------------|-------------|
| `artifact_update` | `event: artifact_update` | Streaming artifact chunks (token-by-token LLM output) |
| `status_update` | `event: status_update` | Task status changes, thinking/progress messages |
| `message` | `event: message` | Direct agent message |
| (any other key) | `event: partial` | Legacy/non-A2A fallback for backward compatibility |

### Stamping taskId and contextId

Before broadcasting, the gateway stamps `taskId` and `contextId` into the
SSE event data from the task record in the DB. This is required because actors
emit FLY dicts without these fields (they only have access to envelope
headers, not the A2A task metadata at the protocol level).

For A2A event types (`artifact_update`, `status_update`):
- Read the task record to get `task_id` and `context_id`
- Inject `"taskId"` and `"contextId"` into the top-level event object
  (e.g., `{"taskId": "...", "contextId": "...", "artifact": {...}, ...}`)

For legacy `partial` events:
- No stamping needed (non-A2A clients do not expect these fields)

### Handler implementation

```go
func (h *MeshHandler) HandleMeshFly(w http.ResponseWriter, r *http.Request) {
    // 1. Parse task ID from URL path
    // 2. Decode FLY dict from request body
    // 3. Determine SSE event type from top-level key
    // 4. If A2A event: stamp taskId and contextId from task record
    // 5. Persist to task_updates table (partial_payload column)
    // 6. Broadcast to SSE subscribers with correct event type
}
```

## Files to Modify

- `src/asya-gateway/internal/handlers/mesh.go` — rename handler, implement
  A2A event type detection and stamping logic
- `src/asya-gateway/cmd/gateway/main.go` — update route registration
- `src/asya-sidecar/internal/progress/reporter.go` — update FLY forwarding
  URL from `/partial` to `/fly`
- All test files referencing `/partial` in both gateway and sidecar

## Testing

Update all existing tests that reference the `/partial` endpoint to use `/fly`:
- Gateway handler tests: rename test functions, update URL paths
- Sidecar reporter tests: update expected URL in HTTP mocks
- Integration tests: update any hardcoded `/partial` paths

New tests for A2A-native event translation:
- FLY dict with `artifact_update` key -> broadcasts `event: artifact_update`
  with `taskId` and `contextId` stamped
- FLY dict with `status_update` key -> broadcasts `event: status_update`
  with `taskId` and `contextId` stamped
- FLY dict with `message` key -> broadcasts `event: message` with `taskId`
  and `contextId` stamped
- FLY dict with unknown key (e.g., `{"token": "hello"}`) -> broadcasts
  `event: partial` without stamping (legacy fallback)
- Verify `taskId` and `contextId` values match the task record in DB

## Dependencies

- T7 (`1c0d/1qdvt8`): Handler wiring and endpoint layout must be in place
  before renaming routes within the new namespace structure
