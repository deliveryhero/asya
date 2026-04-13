---
title: ListTasks with cursor pagination
status: merged
priority: 2
parent: emmc5
---

## Objective

Implement `tasks/list` (A2A method) / `GET {base}/a2a/tasks` endpoint with cursor-based pagination.

## Scope

### 1. Add `List` method to internal TaskStore

New PostgreSQL query with `LIMIT/OFFSET` and `WHERE` clauses for filtering:

| Param | Type | Description |
|-------|------|-------------|
| `context_id` | string | Filter by context |
| `status` | TaskState | Filter by state |
| `page_size` | int | Items per page (default 50, max 100) |
| `page_token` | string | Cursor for next page |
| `history_length` | int | Messages per task (default 0) |
| `status_timestamp_after` | timestamp | Filter by status update time |
| `include_artifacts` | bool | Include artifacts (default false) |

### 2. Add `List` to A2AStoreAdapter

```go
func (a *A2AStoreAdapter) List(
    ctx context.Context,
    req *a2a.ListTasksRequest,
) (*a2a.ListTasksResponse, error)
```

Translate filters and delegate to internal store.

### 3. Wire endpoint in handler

Register `tasks/list` JSON-RPC method and `GET {base}/a2a/tasks` HTTP route.

## References

- RFC sections 7.4 (ListTasks), 5.5 (context filtering), 6.4 (TaskStore Adapter)

## Acceptance Criteria

- Cursor-based pagination works with `page_size` and `page_token`
- Filtering by `context_id` and `status` works correctly
- `history_length` controls how many messages are included per task
- Unit tests in `internal/a2a/list_tasks_test.go`
