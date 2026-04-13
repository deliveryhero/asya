---
title: "Implement GET /tasks/{id} endpoint"
status: merged
priority: 2
tags:
  - pr:202
---

Add A2A-compliant task status endpoint.

## Requirements
- GET /tasks/{task_id} - Retrieve full task state
- Return A2A Task object with status, artifacts, history

## Response Format
```json
{
  "id": "task-123",
  "context_id": "ctx-456",
  "status": {
    "state": "working",
    "message": {...},
    "timestamp": "..."
  },
  "artifacts": [
    {"artifact_id": "...", "name": "...", "parts": [...]}
  ],
  "history": [
    {"message_id": "...", "role": "user", "parts": [...]}
  ],
  "metadata": {...}
}
```

## Task States
- submitted, working, input_required, completed, failed, cancelled, rejected, auth_required

## Implementation
- Replace current /envelopes/{id} handler
- Translate internal envelope to A2A Task format
- Include full message history if available

## Error Handling
- 404 TaskNotFoundError if task doesn't exist
- Include error details in response

## Testing
- Unit test for task format
- Test all status states
- Test 404 handling


---
_Migrated from beads `asya-2n8`_
