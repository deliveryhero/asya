---
title: "Sidecar error logging: log runtime error content and distinguish success/error frames"
priority: 1 # high
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/debt/msic.sidecar-does-not-log-runtime-error-content-before
  - branch:debt/msic.sidecar-does-not-log-runtime-error-content-before
  - pr:344
---





## Bug

When the runtime returns an error (handler exception, envelope validation
failure, etc.), **neither** the sidecar nor the runtime log the error content.
The operator must check x-sump consumer logs to find the traceback.

### Sidecar (Go)

The sidecar routes the message to x-sump but **never logs what the error was**.
The sidecar logs show:

```
INFO  "Calling runtime" id=demo actor=analyze
INFO  "Runtime call completed" id=demo duration=51ms frames=1
INFO  "Pub/Sub message published" topic=asya-demo-skaffold-x-sump
```

There is no ERROR-level log between "Calling runtime" and the x-sump
publish. The operator has no idea what went wrong without checking
x-sump consumer logs or the runtime container logs (which may also
not show the error if the crash happens in the runtime framework
code, not the handler).

## Root Cause

In `router.go` line ~929-949, the `onDownstream` callback:

```go
onDownstream := func(frame runtime.RuntimeResponse, index int) {
    if frame.IsError() {
        dispatchErr = r.handleErrorResponse(ctx, msg, frame, startTime)
        streamHalted = true
        return  // <-- no logging of frame.Error or frame.Details
    }
    // ...
}
```

Then at line ~958:
```go
slog.Info("Runtime call completed", "id", msg.ID, "duration", runtimeDuration, "frames", downstreamCount)
```

This logs "completed" with frame count but doesn't distinguish success
frames from error frames. The `handleErrorResponse` function also does
not log the error content — it goes straight to policy matching and
`sendRetryFailure`.

## Expected Behavior

The sidecar should log the runtime error at ERROR level before routing
to x-sump:

```
ERROR "Runtime returned error" id=demo actor=analyze error="TypeError: 'NoneType' object is not iterable" type="TypeError"
INFO  "Routing to error queue" id=demo queue=x-sump
```

The "Runtime call completed" log should also indicate whether frames
were success or error:

```
INFO  "Runtime call completed" id=demo duration=51ms frames=1 status=error
```

## Impact

Without this log, debugging runtime errors requires:
1. Checking x-sump consumer logs (may not be running)
2. Checking the runtime container logs (may not show the error if it
   happens in the runtime framework, not the handler)
3. `kubectl exec` into the pod and manually testing the handler

This was discovered during the Skaffold demo (aint vppe) when a test
message with incomplete envelope (`route.prev` missing) caused a
`TypeError` in the runtime's `_AbiContext.__init__`. The sidecar gave
zero indication of what went wrong — just silently routed to x-sump.

## Suggested Fix

Add an `slog.Error` in the `onDownstream` callback when `frame.IsError()`:

```go
if frame.IsError() {
    slog.Error("Runtime returned error",
        "id", msg.ID,
        "actor", r.cfg.ActorName,
        "error", frame.Error,
        "errorType", frame.Details.Type,
    )
    dispatchErr = r.handleErrorResponse(ctx, msg, frame, startTime)
    streamHalted = true
    return
}
```

### Runtime (Python)

The runtime also fails to log handler errors visibly. In `asya_runtime.py`,
`_stream_sse_response` catches exceptions and calls
`logger.exception("Error during SSE streaming")` (line ~1262), but the log
output **does not appear in `kubectl logs`**. The error is returned as an SSE
error event to the sidecar but never visibly logged in the runtime container.

Runtime container logs show ONLY startup — no handler calls, no errors:
```
INFO  Asya Actor Runtime starting with handler: 'sentiment_actors.handler.analyze'
INFO  Loading function handler: module=sentiment_actors.handler function=analyze
INFO  HTTP server bound to /var/run/asya/asya-runtime.sock
INFO  Runtime ready signal created: /var/run/asya/runtime-ready
# (nothing else — the TypeError is swallowed)
```

Possible causes:
- Python stdout buffering (not flushed before SSE response completes)
- `BaseHTTPServer` suppresses handler thread logs
- Missing `PYTHONUNBUFFERED=1` in the runtime container env

**Suggested fix**: Ensure `logger.exception()` output flushes to stdout.
Add `sys.stdout.flush()` / `sys.stderr.flush()` after exception logging,
or set `PYTHONUNBUFFERED=1` in the sidecar composition's env for the
runtime container.
