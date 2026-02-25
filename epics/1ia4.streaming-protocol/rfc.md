# RFC: Streaming Protocol — Upstream Partial Events

**Status**: Accepted
**Date**: 2026-02-23
**Updated**: 2026-02-25
**Epic**: 1ia4.streaming-protocol
**Depends on**: 1fbe.redesign-protocol-sidecar-runtime (HTTP-over-Unix-socket)

---

## 1. Problem Statement

AI workloads (LLM inference, agentic loops) produce **partial results** during processing:
token-by-token text generation, intermediate reasoning steps, progress indicators.
Users expect to see these in real-time via the gateway's SSE stream.

Currently, the sidecar-to-gateway communication only supports **progress updates**
(received/processing/completed status per actor). There is no mechanism to forward
arbitrary streaming data from a handler to the gateway during processing.

---

## 2. Design Decision: Transport-Level, Not Payload-Level

Partial events are **transport-level concerns** — they flow directly from the
producing actor's sidecar to the gateway via HTTP. They never enter a message
queue and are never routed to other actors.

### Why not queue-based routing for partials?

The earlier agentic-compiler RFC (sections 10-11) proposed a `partial=true` field
in the message payload with `ASYA_PARTIAL_EVENTS_ROUTE` env var for queue-based
routing. This design is **rejected** for three reasons:

**1. Latency**: Streaming must be fast. Queue-based routing adds publish/consume
overhead (10-100ms per hop) which destroys the real-time streaming experience.
HTTP direct from sidecar to gateway is sub-millisecond on the same cluster network.

**2. Context loss**: Any code that an actor executes before/after receiving a
partial event would need to run in the receiving actor's context. That actor
lacks the producing actor's state — model weights, conversation history,
intermediate buffers. The partial event is meaningless without the producer's
context.

**3. No back-pressure**: In a queue-based actor system, there is no communication
channel from consumer back to producer. A consumer cannot `break` out of a
stream — `GeneratorExit` cannot propagate across a queue boundary. The producer
has no way to know it should stop yielding. This makes constructs like
`async for event in agent_llm(prompt): yield event` impossible to implement
correctly.

### Compiler restriction

The flow compiler MUST forbid re-yielding partial events across actor boundaries:

```python
# FORBIDDEN — compiler must reject this
async for event in agent_llm(prompt):
    yield event  # Cannot forward partials through queues

# ALLOWED — delegate streaming to the callee actor
yield from agent_llm(prompt)  # Callee's sidecar streams directly to gateway
```

The `yield from` form works because the callee actor's runtime produces the
partial events, and its own sidecar forwards them directly to the gateway.
No intermediate actor is involved.

---

## 3. Architecture

### Terminology layers

| Layer | Runtime -> Sidecar | Sidecar -> Gateway | Gateway -> Client |
|---|---|---|---|
| Direction-based | `event: upstream` | — | — |
| Direction-based | `event: downstream` | — | — |
| Semantics-based | — | `POST /tasks/{id}/partial` | `event: partial` |
| Semantics-based | — | `POST /tasks/{id}/progress` | `event: update` |

The runtime-to-sidecar protocol uses **directional** naming (upstream/downstream)
because the sidecar must decide where to route each event. The sidecar-to-gateway
and gateway-to-client protocols use **semantic** naming (partial/update) because
the data meaning matters more than direction at that layer.

### Event flow

```
Runtime (generator handler)
    |
    | HTTP-over-Unix-socket (SSE stream)
    v
Sidecar
    |
    |-- upstream events --> POST /tasks/{id}/partial --> Gateway --> event: partial
    |
    |-- downstream events --> Queue --> Next actor
    |
    |-- done event --> Close connection
```

### SSE event types (Runtime -> Sidecar)

The HTTP-over-Unix-socket protocol (from epic 1fbe) uses Server-Sent Events
for generator handler responses:

| Event | Meaning | Sidecar action |
|---|---|---|
| `downstream` | Result frame for next actor | Route to next actor's queue |
| `upstream` | Partial frame for gateway | HTTP POST to gateway |
| `done` | Generator exhausted | Close connection |
| `error` | Handler exception mid-stream | Report to x-sump |

### Upstream event format

```
event: upstream
data: {"payload": {"type": "text_delta", "delta": "The capital"}}
```

The `data` field contains only a `payload` — no route, no headers. Upstream
events are not routable messages; they are ephemeral streaming data.

### Sidecar -> Gateway forwarding

The sidecar forwards upstream events to the gateway via `ForwardPartial()`
in `progress.Reporter`:

```
POST /tasks/{task_id}/partial
Content-Type: application/json

{"payload": {"type": "text_delta", "delta": "The capital"}}
```

Request body is limited to 1MB (`http.MaxBytesReader`). Errors are propagated
to the caller (logged as warnings by the router). If the gateway is
unreachable, partial events are dropped — they are ephemeral by design.

### Gateway -> Client delivery

The gateway receives upstream events and:

1. Stores them in the task's event history (for late-joining SSE clients)
2. Pushes them to connected SSE clients watching this task

SSE clients receive partial events with `event: partial`:

```
event: partial
data: {"type": "text_delta", "delta": "The capital"}
```

Regular progress updates continue using `event: update` (unchanged).

---

## 4. Error Handling

### Mid-stream error

If a generator handler raises an exception after yielding some upstream events:

```
event: upstream
data: {"payload": {"token": "The capi"}}

event: upstream
data: {"payload": {"token": "The capital of"}}

event: error
data: {"error": "processing_error", "details": {"message": "LLM connection lost"}}
```

**Sidecar behavior**:

1. Upstream events already forwarded to gateway are **NOT recalled**
   (they are ephemeral — the client already received them)
2. Any downstream events already emitted continue independently
   (they are autonomous messages in queues)
3. The original message is routed to **x-sump** with error details
4. The `done` event is NOT sent (error terminates the stream)
5. Gateway receives the error via the normal final-status path
   (x-sump reports `status.phase=failed` to gateway)

### Gateway behavior on error after partials

The gateway should:

1. Send an `error` SSE event to connected clients
2. Mark the task as `failed`
3. Preserve the partial events in history (for debugging/replay)

Clients are responsible for handling the error event and discarding
or displaying the partial data as appropriate.

### x-sink behavior

**x-sink never sees upstream events.** Upstream events bypass the queue
system entirely. x-sink only receives the final downstream result (if any)
when the route is exhausted — same as today.

---

## 5. Lifetime of Upstream Events

| Property | Value |
|---|---|
| Durability | Ephemeral (not persisted in queues) |
| Delivery guarantee | Best-effort (fire-and-forget to gateway) |
| Storage | Gateway task event history (PostgreSQL) |
| Retention | Same as task retention policy |
| Replay | Late-joining SSE clients receive historical events |
| Rollback | None — already-sent events cannot be recalled |

---

## 6. Scope Boundary

This RFC covers the transport of upstream partial events from
runtime to gateway. Remaining work tracked within this epic:

- Compiler restriction: reject `async for` / `yield from` across actor boundaries (task within this epic)
- Integration test: full streaming path `runtime -> sidecar -> gateway -> SSE client` (task within this epic)

Out of scope:

- Queue-based partial event routing (`ASYA_PARTIAL_EVENTS_ROUTE` — rejected, see Section 2)
- Client-side partial event assembly or rendering
- Partial event filtering or transformation in intermediate actors
