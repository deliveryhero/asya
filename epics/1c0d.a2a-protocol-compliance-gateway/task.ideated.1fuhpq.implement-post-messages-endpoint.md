---
title: Implement POST /messages endpoint
priority: 2 # medium
type: task
---





Add A2A-compliant message endpoint to create or continue tasks.

## Requirements
- POST /messages - Create new task or continue existing
- Accept A2A Message format with parts[], role, context_id, task_id
- If task_id provided: continue existing task (human-in-the-loop resume)
- If no task_id: create new task

## Request Format
```json
{
  "message_id": "msg-123",
  "context_id": "ctx-456",
  "task_id": "task-789",  // optional, for continuation
  "role": "user",
  "parts": [
    {"text": "...", "media_type": "text/plain"},
    {"data": {...}, "media_type": "application/json"}
  ]
}
```

## Response Format
```json
{
  "task_id": "task-xyz",
  "status": {"state": "submitted", "timestamp": "..."},
  "context_id": "ctx-456"
}
```

## Implementation
- Add handler HandleMessage in handlers.go
- Translate A2A message to Asya envelope
- Store A2A headers in envelope.headers
- Queue to first actor

## Testing
- Unit test for message parsing
- Integration test for task creation
- Test continuation flow (task_id provided)


---
_Migrated from beads `asya-u76`_
