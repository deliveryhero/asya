# RFC: Streaming Protocol — Upstream Events

**Status**: Accepted (implemented)
**Date**: 2026-02-23
**Updated**: 2026-02-28
**Epic**: 1ia4.streaming-protocol
**Depends on**: 1fbe.redesign-protocol-sidecar-runtime (HTTP-over-Unix-socket)

> **Note**: This RFC describes the streaming *architecture* — the transport-level
> decision that upstream events bypass queues and flow direct to the gateway.
> This architecture is implemented and working. The *handler-side interface*
> (how actors produce upstream events) is evolving from `partial: True` dict
> keys to the ABI `FLY` verb — see epic 1l01. The *wire protocol naming*
> (partial → stream) is tracked in epic 1l02.

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

The flow compiler MUST forbid re-yielding streaming events across actor
boundaries:

```python
# FORBIDDEN — compiler must reject this
async for event in agent_llm(prompt):
    yield event  # Cannot forward streaming events through queues
```

> **Update (2026-02-28)**: Epic 1l04 simplifies this further — the Flow DSL
> now uses **only `await`** for actor calls. The compiler already rejects
> `async for`, `yield`, and `yield from` as unsupported flow constructs. The
> streaming rationale (this section) provides the *why* behind that rejection.
>
> Streaming happens transparently: each actor's sidecar forwards `FLY` events
> (ABI) / upstream SSE events directly to the gateway. No flow-level construct
> is needed.

---

## 3. Architecture

### Terminology layers

| Layer | Runtime -> Sidecar | Sidecar -> Gateway | Gateway -> Client |
|---|---|---|---|
| Direction-based | `event: upstream` | — | — |
| Direction-based | `event: downstream` | — | — |
| Semantics-based | — | `POST /tasks/{id}/stream` | `event: stream` |
| Semantics-based | — | `POST /tasks/{id}/progress` | `event: update` |

> **Note**: The current codebase still uses `partial` (`POST /tasks/{id}/partial`,
> `event: partial`). Epic 1l02 renames these to `stream` to match the ABI
> terminology. The runtime→sidecar layer (`event: upstream`) is unchanged.

The runtime-to-sidecar protocol uses **directional** naming (upstream/downstream)
because the sidecar must decide where to route each event. The sidecar-to-gateway
and gateway-to-client protocols use **semantic** naming (stream/update) because
the data meaning matters more than direction at that layer.

### Event flow

```
Runtime (generator handler)
    |
    | HTTP-over-Unix-socket (SSE stream)
    v
Sidecar
    |
    |-- upstream events --> POST /tasks/{id}/stream --> Gateway --> event: stream
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

### Handler-side interface

Handlers produce upstream events via the ABI `FLY` verb:

```python
yield "FLY", {"type": "text_delta", "delta": "The capital"}
```

> **Legacy**: The current codebase uses `yield {"partial": True, "type": ...}`.
> Epic 1l01 replaces this with `FLY`. The runtime strips the marker/wraps the
> payload identically in both cases — the wire format is unchanged.

### Upstream event format (Runtime -> Sidecar)

```
event: upstream
data: {"payload": {"type": "text_delta", "delta": "The capital"}}
```

The `data` field contains only a `payload` — no route, no headers. Upstream
events are not routable messages; they are ephemeral streaming data.

### Sidecar -> Gateway forwarding

The sidecar forwards upstream events to the gateway via `ForwardStream()`
in `progress.Reporter`:

```
POST /tasks/{task_id}/stream
Content-Type: application/json

{"payload": {"type": "text_delta", "delta": "The capital"}}
```

> **Legacy**: Current code uses `ForwardPartial()` and `POST /tasks/{id}/partial`.
> Epic 1l02 renames to `ForwardStream()` and `/stream`.

Request body is limited to 1MB (`http.MaxBytesReader`). Errors are propagated
to the caller (logged as warnings by the router). If the gateway is
unreachable, streaming events are dropped — they are ephemeral by design.

### Gateway -> Client delivery

The gateway receives upstream events and:

1. Stores them in the task's event history (for late-joining SSE clients)
2. Pushes them to connected SSE clients watching this task

SSE clients receive streaming events with `event: stream`:

```
event: stream
data: {"type": "text_delta", "delta": "The capital"}
```

> **Legacy**: Current code sends `event: partial`. Epic 1l02 renames to
> `event: stream`.

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

### Gateway behavior on error after streaming events

The gateway should:

1. Send an `error` SSE event to connected clients
2. Mark the task as `failed`
3. Preserve the streaming events in history (for debugging/replay)

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

This RFC covers the transport of upstream streaming events from runtime to
gateway. The architecture is implemented and working.

### Completed

- Runtime SSE streaming for generator handlers (PR #205)
- Sidecar SSE parser for generator responses (PR #205)
- Sidecar→Gateway forwarding (PR #205)
- Integration test: full streaming path (PR #209)

### Remaining (within this epic)

- Compiler: reject `async for` / `yield from` across actor boundaries (task
  1khyvl, slopped) — scope narrowed by epic 1l04, see note in Section 2

### Tracked in other epics

- **1l01**: ABI protocol — `FLY` verb replaces `partial: True` dict convention
  (handler-side interface change)
- **1l02**: Rename `partial` → `stream` across sidecar, gateway, and wire
  protocol (downstream naming change)

### Out of scope (rejected)

- Queue-based streaming event routing (`ASYA_PARTIAL_EVENTS_ROUTE` — see
  Section 2 for rationale)
- Client-side streaming event assembly or rendering
- Streaming event filtering or transformation in intermediate actors
