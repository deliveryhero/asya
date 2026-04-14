---
title: Blocking mode for SendMessage
status: merged
priority: 2
---

## Objective

Implement blocking mode: when `configuration.blocking: true` in SendMessage request, the gateway holds the HTTP connection until the task reaches a terminal or interrupted state.

## Scope

### 1. Blocking mode handler

**Flow**:
1. Create task and dispatch envelope (same as non-blocking)
2. Subscribe to task events internally (reuse SSE subscription mechanism)
3. Wait until task reaches terminal state (`COMPLETED`, `FAILED`, `CANCELED`, `REJECTED`) or interrupted state (`INPUT_REQUIRED`, `AUTH_REQUIRED`)
4. Return the final `Task` object with artifacts

### 2. Timeout handling

Use the task's `timeout_sec` as the HTTP response timeout. If the task times out, return the task with `status: FAILED`.

### 3. Response format

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "task": {
      "id": "task-789",
      "contextId": "ctx-abc",
      "status": { "state": "COMPLETED", "timestamp": "..." },
      "artifacts": [...]
    }
  }
}
```

## References

- RFC section 9.4 (Blocking Mode), section 15.2 test matrix

## Acceptance Criteria

- `configuration.blocking: true` holds connection until terminal/interrupted state
- Timeout returns task with FAILED status
- Interrupted states (INPUT_REQUIRED, AUTH_REQUIRED) also release the connection
- Unit tests in `internal/a2a/blocking_test.go`
