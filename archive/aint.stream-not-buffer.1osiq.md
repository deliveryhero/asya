---
title: Stream events instead of buffer
status: merged
priority: 2
parent: nlg57
tags:
  - component:sidecar
  - component:runtime
---

## Problem

The sidecar's `parseSSEStream()` (client.go:150) buffers ALL downstream SSE
events in memory, returns them as a `[]RuntimeResponse` batch, and only then
`handleRuntimeResponses()` iterates and sends each to its queue.

```
Runtime yields frame 1 → SSE event: downstream → sidecar appends to slice
Runtime yields frame 2 → SSE event: downstream → sidecar appends to slice
  ... (arbitrary delay between yields) ...
Runtime yields done    → sidecar returns batch → processes all frames
```

The runtime already streams (flushes after each yield). The bottleneck is the
sidecar: it holds frame 1 in memory doing nothing while waiting for frame 2+.

### When this matters

- **Generator handlers with delays between yields**: LLM agent doing tool
  calls with 10-30 second gaps between iterations. Each iteration yields a
  state update. With buffered dispatch, the first iteration's result sits
  idle while the agent processes the second tool call.
- **Fan-out routers**: A compiler-generated fan-out router yields N+1 messages.
  Sub-agent slices (indices 1..N) could start processing immediately as they're
  yielded, rather than waiting for all slices to be generated.
- **Long-running pipelines**: Any generator that produces intermediate results
  over minutes/hours. The pipeline stalls until the generator is fully exhausted.

### When buffering is fine

- Simple routers that yield 1-2 frames with no delay between them
- Short-lived generators that complete in milliseconds

## Design Decisions

### Decision 1: Message ID assignment → Option B (first yield keeps ID)

**Decided**: First downstream yield keeps original `msg.ID`. Subsequent yields
get `uuid4()` + `parent_id = msg.ID`. Sidecar tracks with a boolean
`firstDownstreamSeen` flag.

**Why not Option A (all new UUIDs)**: Most actors yield a single frame. That
single yield MUST preserve `message.id` for gateway progress correlation. The
sidecar can't know at first-yield time whether more frames will follow.

**Why not Option C (handler-assigned IDs)**: Message ID is sidecar
infrastructure, not user concern. Making handlers do `yield "SET", ".id",
uuid4()` for every fan-out message is fragile and error-prone.

**Fan-out constraint**: Fan-out routers MUST yield index 0 (parent payload)
first. This is already the case — the generated router code yields the parent
before sub-agent slices.

### Decision 2: Fan-out setup message ordering → safe, no change needed

Streaming dispatch of fan-out frames is safe. The aggregator uses split-key
S3 and detects completeness by listing — it's inherently order-independent.
The parent payload (index 0) carries `slice_count` which is computed from
the DSL before any yields.

### Decision 3: Error handling mid-stream → document, accept

Already-dispatched downstream frames cannot be recalled (same precedent as
upstream events in 1ia4 RFC Section 4). For partial fan-outs, aggregator TTL
via S3 lifecycle policy handles cleanup. The original message goes to DLQ.

**Action**: Document these failure semantics clearly in the streaming protocol
docs. Cover: partial fan-out (N of M slices dispatched, then error), single-
frame handler error (frame dispatched, cleanup code fails), and interaction
with retry logic.

### Decision 4: Progress reporting → map `done` event to `StatusCompleted`

**Question answered**: Yes, the runtime sends `event: done` to the sidecar
when the generator is fully exhausted. This is the "I have finished" signal.

**Key finding — the corner case doesn't exist**: In Python generators, `done`
(which maps to `StopIteration`/`StopAsyncIteration`) fires AFTER all user
code has executed, including code after the last yield:

```python
async def handler(state):
    result = await llm_call(state)
    state["result"] = result
    yield state              # ← last yield, SSE downstream dispatched

    await cleanup()          # ← runs BEFORE StopAsyncIteration
    log("finished")          # ← runs BEFORE StopAsyncIteration
    # implicit StopAsyncIteration when function returns
```

Runtime code (`_stream_async_gen`, line 1316):
```python
async for payload_value in user_func(message["payload"]):
    self._emit_sse_event(payload_value, input_route)
# ↑ for-loop exits only after StopAsyncIteration (all user code done)
self.wfile.write(b"event: done\ndata: {}\n\n")  # ← "I'm done"
```

The `async for` loop blocks between last yield and StopAsyncIteration while
post-yield code runs. Only then does the runtime send `done`. So `done`
already means "generator fully exhausted, ALL user code finished."

**Progress lifecycle with streaming dispatch**:

```
Message arrives         → StatusReceived
Before calling runtime  → StatusProcessing
First downstream frame  → dispatch to queue (no progress change)
  ... more frames ...   → dispatch to queue (no progress change)
done event              → StatusCompleted (report to gateway + ack message)
error event             → StatusFailed (report to gateway + route to x-sump)
```

### Decision 5: No batching of last frame + done → always separate events

**Decided**: The runtime always sends `done` as a separate SSE event after the
last downstream frame. The sidecar always sends a separate HTTP request to the
gateway for `StatusCompleted`. No attempt to batch them.

**Why batching was rejected**:

- **Runtime can't batch**: Python generators don't expose "is this the last
  yield?" — the runtime only learns the generator is exhausted when
  `__anext__()` raises `StopAsyncIteration`, by which time the last frame
  has already been flushed to the Unix socket.

- **Sidecar can't reliably peek**: A `bufio.Reader.Peek()` approach was
  considered — check if `done` bytes are already in the read buffer after
  receiving the last downstream event. But the sidecar (Go) typically reads
  faster than the runtime (Python) writes, so the downstream event is
  consumed before `done` is written. The peek is probabilistic, not
  guaranteed, and timing-dependent.

- **No ordering race**: Unix sockets are ordered byte streams. The downstream
  event always arrives before `done`. The sidecar processes events
  sequentially in the same goroutine, so `StatusCompleted` is always
  reported AFTER the last frame dispatch completes. No race.

- **Cost is negligible**: One extra SSE event parse (nanoseconds) + one HTTP
  POST to gateway (~1ms). Handler execution is seconds. Not worth optimizing.

**Message acknowledgment**: The sidecar should NOT ack the incoming queue
message until `done` arrives. This ensures that if the sidecar/runtime crashes
between dispatching a downstream frame and sending `done`, the original
message is redelivered (and re-processed). Already-dispatched frames may
produce duplicates downstream, but that's the same at-least-once guarantee
as the rest of the system.

## Design Summary

**Streaming dispatch** (Option B + done-based completion):

1. `parseSSEStream()` calls callbacks for each event instead of buffering
2. First downstream frame: dispatch immediately with original `msg.ID`
3. Subsequent downstream frames: dispatch with `uuid4()` + `parent_id`
4. `upstream` events: forward to gateway (unchanged)
5. `done` event: report `StatusCompleted` to gateway, ack incoming message
6. `error` event: report failure, route to x-sump, do NOT ack (redelivery)

The signature changes from:
```go
func (c *Client) CallRuntime(...) ([]RuntimeResponse, error)
```
to:
```go
func (c *Client) CallRuntime(..., onDownstream func(RuntimeResponse, int)) error
```

Where `onDownstream(frame, index)` dispatches each frame to its queue
immediately. The `int` index tracks yield position (0 = first = keeps ID).

`handleRuntimeResponses()` is eliminated — its logic moves into the
`onDownstream` callback and the `done`/`error` event handlers inside
`parseSSEStream`.

## References

- Fan-out RFC: `.aint/epics/.closed/1c7i.stateful-fanin-fanout/rfc.md`
  (ADR-3: origin_id, yield order, ID assignment)
- Sidecar SSE parsing: `src/asya-sidecar/internal/runtime/client.go:150`
- Router frame handling: `src/asya-sidecar/internal/router/router.go:259`
- 1fbe epic: `.aint/epics/.closed/1fbe.redesign-protocol-sidecar-runtime/epic.md`
  (SSE protocol design, `done` event definition)
- 1ia4 RFC Section 4 (error handling for already-emitted events)
- Runtime streaming: `src/asya-runtime/asya_runtime.py:1316` (`_stream_async_gen`)
