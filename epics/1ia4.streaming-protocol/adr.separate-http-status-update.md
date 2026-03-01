# ADR: Separate HTTP request for message status update

**Status**: Accepted
**Date**: 2026-03-01
**Context**: Streaming dispatch (task 1osiao)

## Decision

The sidecar always sends the message status update (`StatusCompleted`) to
the gateway as a **separate HTTP request**, triggered by the `done` SSE
event. It does not attempt to batch the status update with the last
downstream frame dispatch.

## Context

When the sidecar switches from buffered to streaming dispatch (dispatching
each downstream frame immediately as it arrives via SSE), the question
arose: can we embed "done" into the last downstream frame and batch the
queue dispatch + status update into one logical operation?

This would save one HTTP round-trip to the gateway (~1ms) per message.

## Options Considered

### Option 1: Batch at runtime level — runtime tags last frame with done flag

The runtime would embed a `done: true` flag in the last `event: downstream`
SSE event, so the sidecar receives one event meaning "dispatch this frame
AND report completed."

**Rejected.** Python generators do not expose whether the current yield is
the last one. The runtime discovers this only when `__anext__()` raises
`StopAsyncIteration` — by which time the last frame has already been flushed
to the Unix socket. The only way to tag it is a one-frame lookahead buffer
(hold each frame, advance the generator, if `StopIteration` → tag as last).
This adds latency equal to the time between yields — defeating the purpose
of streaming dispatch for the multi-yield-with-delays case (the exact
scenario that motivates the change).

### Option 2: Batch at sidecar level — peek read buffer for done

After receiving a downstream event, the sidecar checks if `done` is already
in the `bufio.Reader` buffer via `Peek(Buffered())`. If yes, it processes
both in one step.

**Rejected.** The peek is probabilistic, not guaranteed. The sidecar (Go)
typically reads faster than the runtime (Python) writes. After the runtime
flushes the last downstream event to the Unix socket, the sidecar consumes
it before the runtime writes `done` (which requires Python to call
`__anext__()`, get `StopAsyncIteration`, exit the for-loop, and write the
done event — microseconds of Python execution). By the time the sidecar
checks `Buffered()`, the buffer is likely empty. This creates a timing-
dependent optimization that works sometimes but cannot be relied upon.

### Option 3: Short non-blocking wait at sidecar level

After receiving a downstream event, the sidecar waits a small duration
(e.g., 50-100μs) for `done` to arrive before dispatching.

**Rejected.** Adds latency to every non-last frame. For generators with
many yields (fan-out routers emitting N+1 messages), this adds N * 50μs
of unnecessary delay.

### Option 4 (chosen): Always separate done event and HTTP request

The runtime sends `done` as a separate SSE event. The sidecar sends
`StatusCompleted` to the gateway as a separate HTTP POST.

## Rationale

1. **No ordering race.** Unix sockets are ordered byte streams — `done`
   always arrives after the last downstream event. The sidecar processes
   events sequentially in one goroutine, so `StatusCompleted` is always
   reported after the last frame dispatch completes.

2. **done = generator fully exhausted.** In Python generators,
   `StopIteration` fires after ALL user code has executed, including code
   after the last `yield`. The runtime sends `done` only after the for-loop
   exits. There is no corner case where `done` is sent while user code is
   still running.

3. **Cost is negligible.** One SSE event parse (nanoseconds) + one HTTP
   POST to the gateway (~1ms on cluster network). Handler execution time
   is seconds (LLM inference). The ~1ms overhead is unmeasurable in
   practice.

4. **Simple and correct.** No timing dependencies, no probabilistic
   optimizations, no buffering. The sidecar's SSE parsing loop is
   straightforward: dispatch on downstream, forward on upstream, complete
   on done, fail on error.

## Consequences

- Each generator handler invocation results in one extra HTTP request to
  the gateway (StatusCompleted) compared to a hypothetical batched approach.
- The sidecar MUST NOT ack the incoming queue message until `done` arrives.
  If the sidecar crashes between dispatching a downstream frame and receiving
  `done`, the original message is redelivered (at-least-once semantics).
