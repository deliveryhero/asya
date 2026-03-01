---
title: "Challenge buffered parseSSEStream: stream downstream events immediately"
priority: 2 # medium
type: task
tags:
  - type:research
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

## Design Challenges

### Challenge 1: Message ID assignment

Current logic (router.go:620-632):

```go
msgID := msg.ID
var parentID *string
if totalResponses > 1 && index > 0 {
    msgID = uuid.New().String()
    parentID = &msg.ID
}
```

The sidecar decides ID assignment based on `totalResponses` and `index`. With
streaming dispatch, when the first frame arrives, the sidecar doesn't know
whether more frames will follow. Options:

**Option A: Always assign fresh UUIDs (all frames get new IDs)**

Every downstream frame gets `id = uuid4()`, `parent_id = original_msg.id`.
Including the first one. This breaks the current invariant that "first yield
keeps original message.id", which fan-out depends on (ADR-3 in 1c7i RFC:
index 0 keeps the original ID so the aggregator can restore it on the merged
envelope).

Impact: Fan-out protocol (x-asya-fan-in) uses `origin_id` from the header,
NOT from `message.id`. So the aggregator doesn't care about `message.id`.
But gateway tracking uses `message.id` to correlate progress updates — if
the first frame gets a new ID, the gateway loses the correlation.

**Option B: First yield keeps original ID, mark subsequent as children**

Keep current behavior: first downstream frame uses `msg.ID`, subsequent get
`uuid4()` + `parent_id`. This works with streaming dispatch — just send each
frame immediately as it arrives. The sidecar tracks whether it's seen the
first downstream frame.

Impact: This is a minimal change. A boolean flag `firstDownstreamSeen` in
the SSE parsing loop suffices. But: what if the first frame is actually a
fan-out index 1 (not the parent payload)? Currently the fan-out router is
designed to yield index 0 first. If we mandate this ordering, Option B works.

**Option C: Explicit ID assignment in the frame itself**

Frames carry their own `id` and `parent_id` fields. The runtime/router sets
them, and the sidecar uses them as-is (no auto-assignment). This gives full
control to the router/handler.

Impact: Breaking change to the wire protocol. Currently the sidecar owns ID
assignment. This would move ownership to the runtime.

### Challenge 2: Fan-out setup message ordering

Current fan-out protocol (from 1c7i RFC):
- Index 0 (parent payload) is yielded first → sent to aggregator queue
- Indices 1..N (sub-agent slices) yielded after → sent to sub-agent queues

The parent payload carries `x-asya-fan-in.slice_count = N+1`. If dispatched
immediately via streaming, the aggregator might receive the parent payload
and attempt completeness detection before all sub-agent slices have even been
dispatched.

**Is this actually a problem?**

No, because the aggregator detects completeness by listing S3 objects. Each
slice writes to its own key. The parent payload arrives at the aggregator,
writes `slice-0.json`, lists → sees only 1 of N+1 → not complete → returns
None. When each sub-agent finishes and arrives at the aggregator, it writes
its slice and checks again. The last arrival detects completeness.

The parent payload knowing `slice_count` upfront is fine — the count is
computed from the DSL before any yields. The only requirement is that the
fan-out router yields the parent payload with the correct count, which it
already does.

**So streaming dispatch is safe for fan-out.** The parent payload can be
dispatched immediately. Sub-agent slices can be dispatched as they're
yielded. The aggregator is tolerant of arrival order.

### Challenge 3: Error handling mid-stream

If the generator errors after some downstream frames have already been
dispatched (with streaming), those frames are now in queues and cannot be
recalled. This is analogous to the existing upstream event semantics (Section
4 of the 1ia4 RFC: "upstream events already forwarded are NOT recalled").

For downstream frames, this is more concerning because dispatched frames
trigger actual actor processing, not just UI updates. A partial fan-out
(3 of 5 slices dispatched, then error) means the aggregator will never reach
completeness.

**Mitigation options**:
- Aggregator TTL: S3 lifecycle policy already cleans up stale aggregation
  state. The partial fan-out will time out and be cleaned up.
- Error propagation: On error mid-stream, send an error message to the
  aggregator or x-sump with the `origin_id`, allowing active cleanup.
- No mitigation: Accept that partial fan-outs are a failure mode. The
  original message is nacked/sent to DLQ. This is the current behavior for
  any sidecar/runtime crash mid-processing.

### Challenge 4: Progress reporting

Currently `handleSuccessResponse` reports progress to the gateway only for
`index == 0`. With streaming dispatch, the sidecar sends the first frame and
reports "completed". But the generator is still running. Should progress be
reported per-frame? Only on the last frame?

**Option**: Report "processing" on first frame, "completed" when `done` event
arrives. This decouples progress reporting from frame dispatch.

## Proposed Direction

**Minimal streaming dispatch** (Option B + safe fan-out):

1. `parseSSEStream()` calls a dispatch callback for each downstream frame
   instead of collecting into a slice
2. First downstream frame keeps original `msg.ID`, subsequent get `uuid4()`
3. Fan-out is safe because aggregator is order-independent
4. Progress reported as "completed" only when `done` event arrives
5. Mid-stream errors: already-dispatched frames proceed independently (same
   semantics as upstream events)

The signature changes from:
```go
func parseSSEStream(body, onUpstream) ([]RuntimeResponse, error)
```
to:
```go
func parseSSEStream(body, onUpstream, onDownstream) error
```

Where `onDownstream` sends each frame to its queue immediately.

## References

- Fan-out RFC: `.aint/epics/.closed/1c7i.stateful-fanin-fanout/rfc.md`
  (ADR-3: origin_id, yield order, ID assignment)
- Sidecar SSE parsing: `src/asya-sidecar/internal/runtime/client.go:150`
- Router frame handling: `src/asya-sidecar/internal/router/router.go:259`
- 1ia4 RFC Section 4 (error handling for already-emitted events)
