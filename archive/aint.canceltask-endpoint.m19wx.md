---
title: CancelTask endpoint
status: merged
priority: 2
---

## Objective

Implement `tasks/cancel` (A2A method) / `POST {base}/a2a/tasks/{id}:cancel` endpoint. The sidecar 410 Gone handling is already merged (PR from Phase 1).

## Scope

### 1. CancelTask endpoint

**Flow**:
1. Validate task exists and is not in terminal state
2. Set task status to `canceled` in TaskStore (DB is authoritative)
3. Return updated Task with `status.state: CANCELED` to client immediately
4. Sidecar discovers cancellation on next `GET /mesh/{id}/status` -> `410 Gone`
5. Sidecar drops the envelope, persists it, and reports final status

**Error**: Return `a2a.ErrTaskNotCancelable` if task is already in terminal state.

### 2. Race condition handling

The envelope may be in a queue, being processed, or waiting pickup. The gateway cannot modify queued messages. The sidecar's progress report -> `410 Gone` response is the handshake that resolves this:

- **Before runtime call**: Sidecar gets 410 on "received" progress -> ack msg, route to x-sink, do NOT call runtime
- **After runtime call**: Sidecar gets 410 on "completed" progress -> ack msg, route to x-sink, do NOT route to next actor

### 3. Wire endpoint

Register `tasks/cancel` JSON-RPC method and `POST {base}/a2a/tasks/{id}:cancel` HTTP route.

## References

- RFC sections 7.5 (CancelTask), progress reporter response codes table
- Sidecar 410 handling already merged

## Acceptance Criteria

- CancelTask returns CANCELED task for active tasks
- Returns `ErrTaskNotCancelable` for terminal-state tasks
- Unit tests for cancel logic and error cases
