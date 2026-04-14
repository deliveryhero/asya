---
title: Import a2a-go v0.3.7 and implement state mapping
status: merged
priority: 2
tags:
  - pr:257
---

## Objective

Add the official `a2a-go` library as a dependency and create bidirectional state
mapping functions between Asya's internal task statuses and A2A's `TaskState` enum.
This replaces the hand-rolled A2A types in `pkg/types/a2a.go` with the canonical
types from the `a2a-go` library and establishes the foundation for all subsequent
A2A integration work.

## Scope

### 1. Import a2a-go v0.3.7

Run `go get github.com/a2aproject/a2a-go@v0.3.7` in `src/asya-gateway/` to add the
library to `go.mod` and `go.sum`. The `a2a-go` library provides:
- Generated Go types from the A2A protobuf schema (`a2a.Task`, `a2a.Message`,
  `a2a.Part`, `a2a.Artifact`, `a2a.TaskState`, etc.)
- Server framework (`a2asrv.NewHandler()`) for JSON-RPC dispatch
- SSE helpers for streaming responses
- Request validation

### 2. Create state mapping functions (RFC Section 5.1)

Create `src/asya-gateway/internal/a2a/state.go` with two functions:

```go
// toA2AState converts an Asya internal TaskStatus to an A2A TaskState.
// Used on outbound responses (GetTask, SendMessage response, SSE events).
func toA2AState(s types.TaskStatus) a2a.TaskState

// fromA2AState converts an A2A TaskState to an Asya internal TaskStatus.
// Used on inbound requests (ListTasks filter, status comparisons).
func fromA2AState(s a2a.TaskState) types.TaskStatus
```

The full 9-state bidirectional mapping (per RFC Section 5.1):

| Asya `TaskStatus`   | A2A `TaskState`            | Category    |
|----------------------|----------------------------|-------------|
| `pending`            | `TaskStateSubmitted`       | Active      |
| `running`            | `TaskStateWorking`         | Active      |
| `succeeded`          | `TaskStateCompleted`       | Terminal    |
| `failed`             | `TaskStateFailed`          | Terminal    |
| `canceled`           | `TaskStateCanceled`        | Terminal    |
| `rejected`           | `TaskStateRejected`        | Terminal    |
| `paused`             | `TaskStateInputRequired`   | Interrupted |
| `auth_required`      | `TaskStateAuthRequired`    | Interrupted |
| `unknown`            | `TaskStateUnknown`         | Error       |

The `toA2AState` function must handle an unrecognized input by returning
`TaskStateUnknown` (defensive default). The `fromA2AState` function should similarly
default to `"unknown"` for unrecognized A2A states.

### 3. Remove hand-rolled A2A types in `pkg/types/a2a.go`

The file `src/asya-gateway/pkg/types/a2a.go` contains hand-rolled A2A types that
duplicate what `a2a-go` provides: `A2ATaskState`, `A2APart`, `A2AMessage`,
`A2AArtifact`, `A2ATask`, `A2ATaskStatus`, `A2AJSONRPCRequest`, `A2AJSONRPCResponse`,
`A2AJSONRPCError`, `A2ASendMessageParams`, `A2ATaskStatusUpdateEvent`,
`A2ATaskArtifactUpdateEvent`, `AgentCard`, `AgentCaps`, `AgentSkill`, and the
`ToA2AState()` function.

These should be replaced by imports from `github.com/a2aproject/a2a-go`. This may
require updating all callers in:
- `internal/a2a/handler.go` (JSON-RPC dispatch, message parsing)
- `internal/a2a/translator.go` (MessageToPayload, TaskToA2ATask)
- `internal/a2a/agent_card.go` (AgentCard generation)
- `internal/a2a/streaming.go` (SSE event types)
- `internal/a2a/lifecycle_handler.go`
- `internal/a2a/task_handler.go`
- `pkg/types/a2a_test.go`

If the migration of all callers is too large for a single task, at minimum:
- Move the `ToA2AState` function out of `pkg/types/a2a.go` into `internal/a2a/state.go`
  (as `toA2AState` using `a2a-go` types)
- Add `fromA2AState` (new, does not exist today)
- Mark `pkg/types/a2a.go` types as deprecated with a TODO referencing this task
- Full caller migration can be a follow-up task

### 4. Unit tests

Create `src/asya-gateway/internal/a2a/state_test.go` covering:
- All 9 Asya-to-A2A mappings (round-trip: `toA2AState` then `fromA2AState` returns
  the original value)
- Unknown/unrecognized input defaults to `TaskStateUnknown` / `"unknown"`
- Table-driven tests for exhaustive coverage

## Files

- `src/asya-gateway/go.mod`, `src/asya-gateway/go.sum` -- updated by `go get`
- `src/asya-gateway/internal/a2a/state.go` -- new file with mapping functions
- `src/asya-gateway/internal/a2a/state_test.go` -- new file with unit tests
- `src/asya-gateway/pkg/types/a2a.go` -- remove or deprecate hand-rolled types

## Acceptance Criteria

- `go build ./...` succeeds with `a2a-go` v0.3.7 imported.
- `toA2AState` and `fromA2AState` correctly map all 9 states bidirectionally.
- Unit tests pass for all state mappings including edge cases.
- No hand-rolled A2A type duplicates the `a2a-go` library (or they are clearly
  marked deprecated with migration plan).
