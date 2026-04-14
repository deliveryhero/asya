---
title: Add context_id support for conversation grouping
status: merged
priority: 2
tags:
  - pr:202
---

Add A2A context_id field to group related tasks into conversations.

## Requirements
- context_id groups multiple tasks into a logical conversation
- Support filtering tasks by context_id
- Persist context_id in database
- Include in all A2A responses

## Database Changes
```sql
ALTER TABLE a2a_tasks ADD COLUMN context_id TEXT NOT NULL DEFAULT '';
CREATE INDEX idx_tasks_context ON a2a_tasks(context_id);
```

## API Changes
- GET /tasks?context_id=ctx-123 - Filter by context
- All task responses include context_id

## Implementation
- Add ContextID field to Task model
- Update TaskStore interface
- Generate context_id if not provided (first message)
- Propagate context_id across task chain

## Testing
- Unit test for context grouping
- Integration test for filtering


_Migrated from beads `asya-r52`_
