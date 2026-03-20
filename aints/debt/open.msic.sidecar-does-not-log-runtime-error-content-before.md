---
title: Sidecar does not log runtime error content before routing to x-sump
priority: 1 # high
---

## Bug

When the runtime returns an error frame (handler exception, validation
error, etc.), the sidecar routes the message to x-sump but **never logs
what the error was**. The sidecar logs show:

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
