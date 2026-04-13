---
title: Implement input_required state for human-in-the-loop
status: open
priority: 2
---

Add support for A2A input_required task state.

## Requirements
- Actors can signal they need human input
- Task transitions to input_required state
- State persists to S3 via happy-end
- Client can resume with POST /messages (with task_id)

## Actor Event Format
```json
{
  "role": "agent",
  "parts": [
    {"text": "Which option?", "media_type": "text/plain"},
    {"data": {"type": "input_request", "options": [...]}, "media_type": "application/json"}
  ]
}
```

## Gateway Handling
1. Receive input_required event from actor
2. Update task state to input_required
3. Persist to S3 via happy-end
4. Store task_id → S3 path mapping in Postgres
5. Notify SSE subscribers

## Resume Flow
1. Client sends POST /messages with task_id
2. Gateway fetches state from S3
3. Creates new envelope with human response
4. Queues to actor
5. Task state → working

## Database Schema Addition
```sql
ALTER TABLE a2a_tasks ADD COLUMN s3_path TEXT;
```

## Testing
- Unit test for state transition
- Integration test for full suspend/resume flow
- Test timeout handling


---
_Migrated from beads `asya-r7d`_
