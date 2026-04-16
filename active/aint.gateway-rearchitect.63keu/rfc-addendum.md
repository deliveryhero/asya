---
title: "RFC Addendum: Review Resolutions"
---

# RFC Addendum: Resolutions from Review

## 1. FLY Events Are Best-Effort

FLY events are ephemeral UX previews, NOT the persistence layer.

- **Pod death**: FLY events in flight are lost. Client reconnects, catches up
  from DB (status only). Partial artifact chunks are gone.
- **Create-subscribe gap**: FLY events emitted before SSE subscription are lost.
  For fast actors (~sub-100ms), initial FLY events may be missed.
- **Artifact data integrity**: actors MUST persist important data to state-proxy
  (S3/GCS). FLY is for live preview only. The final result comes via terminal
  status event (persisted to DB + state-proxy).

No buffering for v1 — keeping things simple. If users report missing initial
FLY events, add brief buffering (~20 LOC) as optimization.

## 2. Rolling Update Resilience

Ketama consistent hashing (nginx `upstream-hash-by`) minimizes disruption:
- Pod removed: ~1/N keys remap (N = replica count)
- Pod added: ~1/N keys move to new pod
- Other keys undisturbed

Combined with:
- `PodDisruptionBudget`: maxUnavailable=1
- Graceful shutdown: SIGTERM → stop accepting, drain existing SSE (30s)
- Client reconnect: catch up from DB

Rendezvous hashing (HRW) noted as alternative for future application-level
routing (better distribution with small cluster sizes 2-5 pods).

## 3. Monotonic Status Ordering

Mesh-api rejects stale status updates using monotonic ordering:

```
pending(0) → running(1) → paused(2) → succeeded/failed/canceled(3)
```

```go
if statusOrder[newStatus] < statusOrder[currentStatus] {
    return // stale, reject
}
```

Handles: MQ redelivery (duplicate processing), network reordering, race
conditions. Terminal statuses (3) can never be overwritten. ~10 LOC.

## 4. Sidecar Pre-Flight Check (New Feature)

Before processing, sidecar checks if the message is still active:

```go
resp := http.Get(gatewayURL + "/api/v1/mesh/" + msg.ID)
if resp.Status == "canceled" || resp.Status == "paused" {
    queue.Ack(msg)      // remove from queue
    sendToSink(msg)     // route to x-sink with canceled status
    return
}
```

Prevents wasted work on user-canceled/paused messages. Filed as separate aint.

## 5. MQ Redelivery (Separate Aint: debt)

When MQ redelivers (visibility timeout), two pods process the same message.
Monotonic status ordering ensures the final status is correct, but duplicate
processing wastes resources. Proper fix (idempotency key, distributed lock)
deferred to debt aint.

## 6. Message Ordering

Asya provides at-least-once delivery, NOT ordered. Within one message, events
arrive in order (sequential route, one actor at a time). Between messages,
no ordering. Monotonic status ordering prevents regression.

## 7. Naming Clarification

```
asya-gateway (deployment unit = K8s Deployment)
├── mesh-api              (:8080 ext, :8081 int)
├── mcp-adapter           (:8082)
├── a2a-adapter           (:8083)
├── state-proxy-mesh      (PG connector, for envelope metadata)
└── state-proxy-envelopes (S3 connector, OPTIONAL, for full envelopes/history)
```

- `asya-gateway` = the deployment (Go module at `src/asya-gateway/`)
- `mesh-api`, `mcp-adapter`, `a2a-adapter` = binaries within the deployment
- `state-proxy-mesh` = PG state-proxy sidecar (mesh-api talks to this)
- `state-proxy-envelopes` = S3 state-proxy sidecar (a2a-adapter talks to this for history)
- Header remains `x-asya-gateway-url` (the deployment name)
- No backward compatibility needed (zero production use cases)

## 8. SSE Event Schema (Asya-Native)

```
event: status
data: {"status":"running","actor":"train-model","progress":50.0,"message":"Step 500/1000"}

event: fly
data: {"text":"token chunk..."}

event: fly
data: {"tool_call":{"name":"search","args":{"q":"..."}}}

event: status
data: {"status":"succeeded","actor":"x-sink"}
```

Three SSE event types: `status`, `fly`. No `id:` field (FLY is ephemeral,
no replay). On reconnect, client catches up from DB (GET /mesh/{id}).

MCP adapter translates: status → MCP progress notification, fly → MCP log
notification, terminal status → MCP CallToolResult. All via mark3labs/mcp-go.

## 9. Fan-Out: Not a Gateway Concern

Fan-out is actor-side:
- First `yield payload` keeps `msg.id`
- Subsequent yields get new UUID with `parent_id = original msg.id`
- Each sub-envelope is independent from the gateway's perspective
- They POST status updates with their own IDs
- No special gateway endpoint needed

## 10. Pause/Resume

Same envelope is paused and resumed (same DB row, status: paused → running):
- Pause: x-pause actor checkpoints to S3, POSTs status "paused" to mesh-api
- Resume: A2A adapter creates new envelope routed to x-resume, mesh-api updates
  original message status from paused → running, recalculates deadline
