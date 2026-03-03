---
title: Implement A2AStoreAdapter wrapping PgStore
priority: 2 # medium
type: task
tags:
  - pr:257
dependencies:
  - 1c0d/1qcmsr
---


## Summary

Create `internal/a2a/store_adapter.go` implementing the `a2asrv.TaskStore`
interface from `a2a-go` v0.3.7. This adapter wraps the existing
`taskstore.PgStore` (the gateway's internal task store) and translates between
Asya's internal task representation and the A2A `Task` proto schema.

Reference: RFC Section 6.4 (TaskStore Adapter).

## Interface

The `a2asrv.TaskStore` interface requires three methods:

```go
type A2AStoreAdapter struct {
    internal taskstore.TaskStore
}

func (a *A2AStoreAdapter) Save(
    ctx context.Context,
    task *a2a.Task,
    event a2a.Event,
    prev a2a.TaskVersion,
) (a2a.TaskVersion, error)

func (a *A2AStoreAdapter) Get(
    ctx context.Context,
    taskID a2a.TaskID,
) (*a2a.Task, a2a.TaskVersion, error)

func (a *A2AStoreAdapter) List(
    ctx context.Context,
    req *a2a.ListTasksRequest,
) (*a2a.ListTasksResponse, error)
```

## Implementation Details

### Save

- Translate `*a2a.Task` to `types.TaskUpdate` via `a2aTaskToUpdate(task, event)`
- Delegate to `a.internal.Update(update)`
- Return new version as `a2a.TaskVersion(task.Status.Timestamp.UnixNano())`
- Handle optimistic concurrency: if `prev` version does not match the current
  stored version, return a conflict error

### Get

- Delegate to `a.internal.Get(string(taskID))`
- If not found, return `a2a.ErrTaskNotFound`
- Reconstruct the full A2A `Task` from two storage layers (RFC Section 5.0):
  - **DB metadata**: `id`, `context_id`, `status` (from `tasks` table)
  - **Payload data**: `history`, `artifacts`, `metadata` (from S3 via the
    payload stored in `payload.a2a.task`)
- Assemble via `internalToA2ATask(task)` which maps:
  - `task.ID` -> `a2aTask.ID`
  - `task.ContextID` -> `a2aTask.ContextID`
  - `task.Status` -> `a2aTask.Status` (using `toA2AState()` from T2)
  - `task.Payload["a2a"]["task"]["history"]` -> `a2aTask.History`
  - `task.Payload["a2a"]["task"]["artifacts"]` -> `a2aTask.Artifacts`
  - `task.Payload["a2a"]["task"]["metadata"]` -> `a2aTask.Metadata`
- Compute version as `a2a.TaskVersion(task.UpdatedAt.UnixNano())`

### List

- Translate `*a2a.ListTasksRequest` filters to internal query parameters
- Requires adding a **new `List` method to `taskstore.PgStore`** with
  cursor-based pagination support:
  - Cursor is an opaque token encoding the last-seen `(updated_at, id)` pair
  - Page size from `req.PageSize` (default and max TBD)
  - Filters: `context_id`, `status` (translated via `fromA2AState()`)
- Assemble each internal task into an A2A `Task` via `internalToA2ATask()`
- Return `*a2a.ListTasksResponse` with `Tasks` and `NextCursor`

### State Translation

Use `toA2AState()` and `fromA2AState()` functions from T2 (task 1c0d/1qcmsr)
to convert between `types.TaskStatus*` constants and `a2a.TaskState*` constants.

### Version Tracking

Versions are timestamp-based: `a2a.TaskVersion(task.UpdatedAt.UnixNano())`.
This provides monotonically increasing versions tied to the last DB update
timestamp, enabling optimistic concurrency checks in `Save`.

## Files

- `src/asya-gateway/internal/a2a/store_adapter.go` — adapter implementation
- `src/asya-gateway/internal/a2a/store_adapter_test.go` — unit tests
- `src/asya-gateway/internal/taskstore/pgstore.go` — add `List` method with
  cursor-based pagination

## Testing

Unit tests in `internal/a2a/store_adapter_test.go` should cover:
- `Save` translates A2A Task to internal update and returns timestamp version
- `Get` reconstructs full A2A Task from DB metadata + payload data
- `Get` returns `a2a.ErrTaskNotFound` for unknown task IDs
- `List` delegates pagination parameters and assembles response
- State translation round-trips correctly (`toA2AState` / `fromA2AState`)
- Version tracking uses `UpdatedAt.UnixNano()`

## Dependencies

- T2 (`1c0d/1qcmsr`): Provides `a2a-go` types, `toA2AState()`, `fromA2AState()`
