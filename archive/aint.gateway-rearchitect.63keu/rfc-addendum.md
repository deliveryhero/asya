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
├── state-proxy-mesh      (pg-kv default; or local-kv for low-infra — see §11)
└── state-proxy-envelopes (S3 connector, OPTIONAL, for full envelopes/history)
```

- `asya-gateway` = the deployment (Go module at `src/asya-gateway/`)
- `mesh-api`, `mcp-adapter`, `a2a-adapter` = binaries within the deployment
- `state-proxy-mesh` = state-proxy sidecar for mesh-api; backend is configurable
- `state-proxy-envelopes` = S3/GCS state-proxy sidecar (a2a-adapter talks to this for history)
- Header remains `x-asya-gateway-url` (the deployment name)
- No backward compatibility needed (zero production use cases)

## 11. State-Proxy Backends for Gateway Mesh State

Three supported backends for `stateProxy.mesh` (see ADR: state-proxy-backends):

| Backend | Use case | Replicas | Notes |
|---|---|---|---|
| `pg-kv` (default) | Production, any scale | any | 1 SQL query for FindExpired |
| `local-kv` | Low-infra, single replica | **1 only** | in-memory or PVC; no external deps |
| `s3kv` / `gcskv` | Actor state analytics | any | NOT recommended for gateway mesh state (see below) |

**S3/GCS is NOT a good gateway mesh state backend.** FindExpired requires
O(n) S3 GETs per cycle — at 1000 active tasks + 5s interval ≈ 12,000 API
requests/minute. Instead, s3kv/gcskv are positioned as **actor state query
tools**: actors persist results to S3/GCS; downstream analytics queries them
via Mango filter. See ADR: state-proxy-backends.

**Actor state analytics (shipped, PR #463):** the primary delivery of the s3kv/gcskv
positioning is `POST /query` on the Python connectors (`s3-buffered-lww`,
`gcs-buffered-lww`). Objects are fetched via the connector's own credential chain
(boto3 / GCS SDK — not DuckDB httpfs, which has MinIO/LocalStack compat gaps) and
queried locally with DuckDB. Per-call limits (`QUERY_MAX_FETCH_BYTES` default 256 MiB,
`QUERY_MAX_FETCH_KEYS` default 1 000) protect container disk. Configurable via
`persistence.config.query.*` in the `asya-crew` Helm chart.

**local-kv single-replica constraint:** in-memory mode is inconsistent across
replicas (no shared state); PVC mode uses ReadWriteOnce block storage (only one
pod can mount). The Helm chart emits a validation error if `backend: local-kv`
and `replicaCount > 1`.

**E2E profile naming convention** reflects the gateway state backend:
- `pubsub-gcs-pg` — Pub/Sub + GCS actor state + pg-kv gateway
- `sqs-s3-pg`     — SQS + S3 actor state + pg-kv gateway
- `sqs-s3-pvc`    — SQS + S3 actor state + local-kv (pvc mode) gateway; no Postgres

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
