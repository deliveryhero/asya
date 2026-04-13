---
title: Implement AsyaExecutor with skill resolution
status: merged
priority: 2
parent: emmc5
dependencies:
  - 1qn6
  - 1qzr
  - 1qv3
tags:
  - pr:257
---

## Summary

Create `internal/a2a/executor.go` implementing the `a2asrv.AgentExecutor`
interface from `a2a-go` v0.3.7. This is the core bridge between the A2A
protocol and the actor mesh: it translates incoming A2A messages into envelopes
and dispatches them to the appropriate actor queue.

Reference: RFC Section 6.3 (AgentExecutor Implementation).

## Interface

```go
type AsyaExecutor struct {
    queueClient   queue.Client
    taskStore     taskstore.TaskStore
    skillRegistry *SkillRegistry
    namespace     string
}

func (e *AsyaExecutor) Execute(
    ctx context.Context,
    reqCtx *a2asrv.RequestContext,
    queue eventqueue.Queue,
) error

func (e *AsyaExecutor) Cancel(
    ctx context.Context,
    reqCtx *a2asrv.RequestContext,
    queue eventqueue.Queue,
) error
```

## Execute Flow

1. **Check for resume**: If `reqCtx.Message.TaskID` is set, look up the task
   in the internal store. If the task exists and its status is `paused`
   (mapped to A2A `INPUT_REQUIRED`), dispatch to `x-resume` instead of the
   normal flow (RFC Section 6.3 resume handling). The resume envelope
   appends the new message to `payload.a2a.task.history` before dispatch.

2. **Resolve skill**: Determine which entrypoint actor to invoke using the
   skill resolution strategy (see below).

3. **Translate message**: Use the message-to-envelope translator (T4) to
   convert the A2A `Message` into an envelope payload. The payload follows
   the `payload.a2a.task` structure from RFC Section 5.0, with the A2A
   `Task` proto fields embedded at `payload.a2a.task.*`.

4. **Set status snapshot**: Stamp `payload.a2a.task.status` with
   `{"state": "submitted", "timestamp": <now>}` (REQUIRED by A2A proto).

5. **Create envelope**: Build a `types.Task` with:
   - `ID` = `string(taskInfo.TaskID)`
   - `ContextID` = `taskInfo.ContextID`
   - `Status` = `types.TaskStatusPending`
   - `Route.Curr` = resolved skill's entrypoint actor
   - `Headers["x-asya-a2a-task-id"]` = task ID
   - `Headers["x-asya-a2a-context-id"]` = context ID
   - `Payload` = translated payload

6. **Dispatch**: Send envelope to the actor queue via `queueClient.SendMessage()`.

7. **Write submitted event**: Write a `TaskStatusUpdateEvent` with state
   `SUBMITTED` to the a2a-go event queue, confirming dispatch.

## Cancel Flow

1. Mark the task as canceled in the internal store via
   `taskStore.Update(types.TaskUpdate{ID: ..., Status: types.TaskStatusCanceled})`
2. Write a `TaskStatusUpdateEvent` with state `CANCELED` to the event queue

## Skill Resolution Strategy (RFC Section 8.3)

The resolution follows a strict priority order:

1. **Explicit skill hint**: Check `request.metadata["skill"]` for an explicit
   skill ID. Match against the tool registry filtered by `a2a_enabled = true`.
   Return an error if the named skill does not exist.

2. **Task continuation**: If `message.TaskID` is set, look up the original
   task's skill from the persisted envelope at
   `payload.a2a.task.metadata.skill`. Reuse the same skill for continuations.

3. **Single skill default**: If exactly one A2A-enabled skill is registered,
   use it automatically. This is the common case for single-purpose gateways.

4. **Reject with guidance**: If multiple skills exist and no hint was provided,
   return a JSON-RPC error (code `-32001`) with a message listing all available
   skills: `"Skill not specified. Available: [skill-a, skill-b, ...]"`.

## Files

- `src/asya-gateway/internal/a2a/executor.go` — executor implementation
- `src/asya-gateway/internal/a2a/executor_test.go` — unit tests

## Testing

Unit tests in `internal/a2a/executor_test.go` should cover:

- **Execute (new task)**: Resolves skill, translates message, dispatches
  envelope with correct headers and payload structure, writes submitted event
- **Execute (resume)**: Detects paused task via `message.TaskID`, dispatches
  to x-resume, appends message to history
- **Execute (skill not found)**: Returns `-32001` error when skill hint
  references nonexistent skill
- **Execute (ambiguous skills)**: Returns `-32001` error listing available
  skills when multiple skills exist and no hint provided
- **Execute (single skill default)**: Auto-selects the sole registered skill
- **Cancel**: Updates task status to canceled, writes cancellation event
- **Cancel (task not found)**: Returns error for unknown task IDs
- **Envelope structure**: Verify `x-asya-a2a-task-id` and
  `x-asya-a2a-context-id` headers, `payload.a2a.task.status` snapshot,
  route configuration

## Dependencies

- T3 (`1c0d/1qn6p7`): Tool registry for skill resolution and `a2a_enabled` filtering
- T4 (`1c0d/1qzr7p`): Message-to-envelope translator for payload conversion
- T5 (`1c0d/1qv3q2`): Store adapter for task lookups during resume detection
