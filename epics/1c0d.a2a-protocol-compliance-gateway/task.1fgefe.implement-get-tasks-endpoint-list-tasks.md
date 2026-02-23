---
title: Implement GET /tasks endpoint (list tasks)
status: open
priority: 3 # low
type: task
---


Add A2A-compliant task listing endpoint.

## Requirements
- GET /tasks - List tasks with optional filtering
- Support query parameters: context_id, status, limit, offset

## Query Parameters
- context_id: Filter by conversation
- status: Filter by state (working, completed, etc.)
- limit: Max results (default 20, max 100)
- offset: Pagination offset

## Response Format
```json
{
  "tasks": [
    {"id": "...", "context_id": "...", "status": {...}},
    ...
  ],
  "next_offset": 20,
  "total_count": 150
}
```

## Implementation
- Add ListTasks method to TaskStore interface
- Implement PostgreSQL query with filters
- Support in-memory store for development

## Testing
- Unit test for filtering
- Test pagination
- Test empty results


---
_Migrated from beads `asya-ahb`_
