---
title: "Implement POST /tasks/{id}:cancel endpoint"
status: open
priority: 3 # low
type: task
---

Add A2A-compliant task cancellation endpoint.

## Requirements
- POST /tasks/{task_id}:cancel - Cancel a running task
- Transition task to 'cancelled' state
- Notify actors to stop processing

## Request Format
```json
{
  "reason": "User requested cancellation"
}
```

## Response Format
```json
{
  "task_id": "...",
  "status": {"state": "cancelled", "timestamp": "..."},
  "message": "Task cancelled successfully"
}
```

## Implementation
- Add Cancel method to TaskStore
- Publish cancellation event to actors
- Update SSE streams with cancellation
- Handle already-completed tasks gracefully

## Sidecar Integration
- Sidecar should check /tasks/{id}/active before processing
- On cancellation, sidecar should stop and ack message

## Error Handling
- 404 if task not found
- 400 if task already in terminal state

## Testing
- Unit test for state transition
- Integration test for cancellation flow
- Test cancellation of completed task


---
_Migrated from beads `asya-78f`_
