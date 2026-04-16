---
description: "Streaming spec: FLY events, SSE delivery, pg_notify cross-process, ephemeral vs persistent"
---

# Streaming Events Reference

Complete reference for all streaming event types in Asya, how they flow through the
system, how they map to client protocols (A2A, MCP, SSE), and when to use each.

---

## Event Types at a Glance

Asya produces three categories of streaming events. Each serves a different purpose,
has different durability guarantees, and reaches clients through different mechanisms.

| Event type | Source | Durability | Frequency | Client delivery |
|---|---|---|---|---|
| **FLY** | Actor handler (`yield "FLY"`) | Ephemeral (in-memory only) | High (30+ events/sec) | SSE via `/stream/{id}` or A2A artifact chunks |
| **Progress** | Sidecar (`POST /mesh/{id}/progress`) | Durable (PostgreSQL) | Low (~3 per actor) | SSE via `/mesh/{id}/stream`, A2A status events |
| **Terminal** | x-sink / x-sump (`POST /mesh/{id}/final`) | Durable (PostgreSQL) | Once per task | SSE final event, A2A `TaskStatusUpdateEvent{Final}` |

### When to use what

| You want to... | Use | Why |
|---|---|---|
| Stream LLM tokens to a UI | **FLY** | Per-token, ephemeral, reaches only live SSE clients |
| Show a progress bar | **FLY** | High-frequency, real-time, no persistence needed |
| Log "actor X started processing" | **Progress** | Low-frequency, persisted, visible in task history |
| Report "task completed with result" | **Terminal** | Durable, triggers A2A `completed` state |
| Send data to downstream actors | **Payload** (`yield payload`) | Routed through message queues, not a streaming event |
| Persist data for pause/resume | **History** (`payload.a2a.task.history`) | Survives checkpointing, readable after resume |

---

## FLY Events

### What they are

FLY events are **ephemeral streaming messages** sent upstream from actor handlers to
connected clients. They bypass message queues entirely and travel via direct HTTP from
sidecar to gateway.

```python
yield "FLY", {"partial": True, "text": "Hello"}
```

### How they flow

```
Actor handler
    yield "FLY", {...}
         |
    Runtime (asya-runtime)
         | sends FLY frame over Unix socket
         v
    Sidecar (asya-sidecar)
         | HTTP POST /mesh/{task_id}/fly
         v
    Mesh Gateway
         | pg_notify('fly', 'task_id:payload')    <- no DB write
         | NotifyFLY() fallback (if PG unavailable)
         v
    PG LISTEN/NOTIFY                              <- in-memory broadcast
         | cross-process delivery to all API gateway replicas
         v
    API Gateway (LISTEN goroutine)
         | dispatches to in-process Subscribe() channels
         v
    SSE clients
```

### Delivery guarantees

- **Ephemeral**: FLY events exist only in memory. They are never written to PostgreSQL.
- **At-most-once**: If no client is connected, the event is silently dropped.
- **No replay**: Clients connecting after a FLY event was sent will never see it.
- **Cross-replica**: PG LISTEN/NOTIFY broadcasts to all API gateway replicas, so the
  client can be on any replica.
- **Buffer**: Each subscriber has a 100-event channel buffer. If a consumer stalls for
  ~3 seconds at 30 events/sec, events are dropped with a warning log.

### SSE event types

The gateway auto-detects the SSE event type from the FLY payload:

| FLY payload key | SSE `event:` type | Use case |
|---|---|---|
| `artifact_update` | `artifact_update` | A2A-structured artifact chunk |
| `status_update` | `status_update` | A2A-structured status |
| `message` | `message` | A2A-structured message |
| *(anything else)* | `partial` | Generic streaming (LLM tokens, progress) |

Most FLY events use the `partial` type. The A2A-specific types are for actors that
want to send protocol-native A2A events directly.

### Payload conventions

```python
# LLM token streaming (most common)
yield "FLY", {"partial": True, "text": "Hello"}

# Progress update
yield "FLY", {"type": "progress", "percent": 45, "message": "Processing..."}

# Status message
yield "FLY", {"type": "status", "message": "Connecting to database..."}

# A2A-native artifact chunk
yield "FLY", {
    "artifact_update": {
        "artifact": {"artifactId": "response", "parts": [{"kind": "text", "text": "Hello"}]}
    }
}
```

---

## Progress Events

### What they are

Progress events report per-actor lifecycle state. They are sent automatically by the
sidecar at three checkpoints as each actor processes an envelope.

### How they flow

Unlike FLY events (which use PG LISTEN/NOTIFY for instant cross-process delivery),
progress events use a traditional write-then-poll pattern. This is acceptable because
progress events are low-frequency (~3 per actor) and must be durable.

```
Sidecar
    POST /mesh/{task_id}/progress
    {"prev": [...], "curr": "actor-b", "next": [...], "status": "processing"}
         |
    Mesh Gateway (HandleMeshProgress)
         | writes to PostgreSQL (tasks + task_updates tables)
         | notifyListeners() for same-process SSE subscribers
         v
    API Gateway (separate process in dual-gateway mode)
         | detects new status via 500ms DB poll
         | (in single-gateway/testing mode: instant via in-process subscription)
         v
    SSE clients / A2A event queue
```

### Lifecycle states

Each actor transitions through three states:

| State | Weight | Meaning |
|---|---|---|
| `received` | 0.1 | Sidecar received the envelope from the queue |
| `processing` | 0.5 | Runtime is executing the handler |
| `completed` | 1.0 | Handler returned, sidecar is routing the result |

Progress percentage is calculated as:
`(len(prev) + status_weight) / total_actors * 100`

Progress is **monotonic** — it never decreases.

### Durability

Progress events are **durable**. They are written to the `tasks` and `task_updates`
tables in PostgreSQL, which means:
- Clients connecting mid-task see replayed progress via `GetUpdates`
- Progress survives gateway restarts
- Progress is visible in `GET /mesh/{id}` responses

---

## Terminal Events

### What they are

Terminal events report the final outcome of a task. They are sent by crew actors:
- `x-sink` reports `succeeded` (normal completion)
- `x-sump` reports `failed` (error after retry exhaustion)
- `x-pause` reports `paused` (human-in-the-loop checkpoint)

### How they flow

Terminal events follow the same write-then-poll pattern as progress events (not
the instant PG NOTIFY path used by FLY). Terminal events are rare (once per task)
so the 500ms poll latency is negligible.

```
x-sink / x-sump
    POST /mesh/{task_id}/final
    {"id": "...", "status": "succeeded", "result": {...}}
         |
    Mesh Gateway (HandleMeshFinal)
         | writes to PostgreSQL
         | notifyListeners() for same-process subscribers
         v
    API Gateway (separate process in dual-gateway mode)
         | detects terminal status via 500ms DB poll
         | (in single-gateway/testing mode: instant via in-process subscription)
         | writes TaskStatusUpdateEvent{Final: true} to A2A event queue
         v
    A2A SSE / MCP response
```

### Terminal statuses

| Status | Meaning | A2A mapping |
|---|---|---|
| `succeeded` | Task completed normally | `completed` |
| `failed` | Task failed after retries | `failed` |
| `canceled` | Client canceled the task | `canceled` |
| `paused` | Actor requested human input | `input_required` |
| `auth_required` | Actor needs authentication | `auth_required` |

---

## Protocol Mapping

### How events reach A2A clients

A2A clients connect via `message/stream` (sendSubscribe). The gateway's
`waitAndRelayEvents` loop translates internal events to A2A SSE events:

| Internal event | A2A SSE event | Persisted? |
|---|---|---|
| FLY (`PartialPayload`) | `TaskArtifactUpdateEvent{Append: true}` | No — `Save()` returns early |
| First FLY for a task | `TaskArtifactUpdateEvent{Append: false}` (creates artifact) | No |
| Terminal status detected | `TaskArtifactUpdateEvent{LastChunk: true}` + `TaskStatusUpdateEvent{Final: true}` | Status only |
| Progress (status change) | *(dropped — prevents feedback loop)* | Already in DB |

The artifact ID for FLY-based chunks is deterministic: `fly-stream`. A2A clients can
assemble the full streaming text by concatenating `TextPart` values from artifact
update events with the same ID.

`Save()` skips PostgreSQL writes for all `TaskArtifactUpdateEvent` events. This
prevents the feedback loop (`eq.Write` -> a2a-go `Process` -> `saveTask` -> `Save` ->
`Update` -> `notifyListeners` -> back to `eq.Write`). Artifact parts accumulate only
in a2a-go's in-memory `Manager.lastSaved`.

### How events reach MCP clients

MCP tool calls return the final result synchronously. For live streaming during
execution, MCP clients connect to `/stream/{id}` SSE endpoint separately.

### How events reach custom UI clients

Custom UIs (chatbots, dashboards) connect to `/stream/{id}` on the API gateway.
This is the recommended path for any client that wants raw FLY events without
A2A or MCP protocol overhead.

```javascript
const eventSource = new EventSource(`/stream/${taskId}`);

eventSource.addEventListener('partial', (e) => {
    const data = JSON.parse(e.data);
    appendToken(data.text);  // render streaming token
});

eventSource.addEventListener('update', (e) => {
    const data = JSON.parse(e.data);
    if (data.status === 'succeeded') {
        eventSource.close();
        showFinalResult(data);
    }
});
```

---

## SSE Endpoints

Two endpoints serve SSE streams. They share the same handler but have different
network exposure:

| Endpoint | Deployment | Access | Use case |
|---|---|---|---|
| `GET /stream/{id}` | API gateway | External (Ingress) | Chatbot UIs, A2A/MCP clients wanting raw FLY |
| `GET /mesh/{id}/stream` | Mesh gateway | Internal (ClusterIP) | Debugging, asya-lab, internal tools |

Both endpoints:
1. Replay historical progress/status updates first (from `task_updates` table)
2. Subscribe to live updates (from in-process `notifyListeners` channels)
3. Stream FLY events as `event: partial` (or A2A-typed events)
4. Send keepalive comments every 15 seconds
5. Close when a terminal status is reached

Note: historical replay includes progress and status updates only. FLY events are
ephemeral and are never replayed.

---

## Architecture: Three-Layer Model

```
+-----------------------------------------------------------+
|  FLY Layer (ephemeral)                                    |
|  Actor yield "FLY" -> sidecar -> mesh gw -> pg_notify     |
|  -> API gw LISTEN -> SSE / A2A artifact chunks            |
|  No persistence. 30+ events/sec. In-memory only.          |
+-----------------------------------------------------------+
|  Protocol Layer (metadata)                                |
|  Sidecar /progress -> mesh gw -> PostgreSQL               |
|  -> API gw 500ms DB poll -> A2A TaskStatusUpdateEvent     |
|  PG stores: status, route, progress %. ~3 events/actor.   |
+-----------------------------------------------------------+
|  Artifact Layer (durable)                                 |
|  Actors write to state-proxy sidecar -> S3/GCS            |
|  Actors return URLs or structured results in payload      |
|  Full payload. On completion only.                        |
+-----------------------------------------------------------+
```

Each layer has a different storage backend, different latency characteristics, and
serves a different audience:

- **FLY**: for UIs that want real-time feedback (tokens, progress bars)
- **Protocol**: for the task lifecycle state machine (submitted -> working -> completed)
- **Artifact**: for the final authoritative result (full response, generated files)

---

## Cross-Process Delivery (Dual-Gateway Mode)

In production, mesh and API gateways run as separate deployments. FLY events cross
this boundary via PostgreSQL LISTEN/NOTIFY:

```
Mesh Gateway pod(s)                API Gateway pod(s)
+------------------+              +------------------+
| HandleMeshFly    |              | LISTEN goroutine |
|   pg_notify()  --+-- PG NOTIFY -+-> dispatchFLY()  |
|                  |   (in-memory) |   notifyListeners|
+------------------+              |   -> SSE clients  |
                                  +------------------+
```

PG LISTEN/NOTIFY is:
- **In-memory**: no WAL, no disk writes, no table storage
- **Broadcast**: all listeners on all replicas receive every notification
- **Fire-and-forget**: if no listener is connected, notifications are silently dropped
- **Payload limit**: 8000 bytes (enforced at the sender; oversized events fall back to
  in-process delivery only)

Each API gateway replica runs a dedicated `*pgx.Conn` (not from pool) for LISTEN.
The connection auto-reconnects on failure with 1-second backoff.

---

## See also

| Topic | Document |
|-------|----------|
| FLY usage guide (actor-side) | [docs/usage/guide-streaming.md](../../usage/guide-streaming.md) |
| ABI protocol (yield verbs) | [docs/reference/specs/abi-protocol.md](abi-protocol.md) |
| Gateway API (all endpoints) | [docs/reference/specs/gateway-api.md](gateway-api.md) |
| Gateway component overview | [docs/reference/components/core-gateway.md](../components/core-gateway.md) |
| Agentic patterns (FLY vs history) | [docs/usage/guide-agentic-patterns.md](../../usage/guide-agentic-patterns.md) |
