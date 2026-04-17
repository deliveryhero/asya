---
title: "RFC: asya-mesh-api + Protocol Adapters Architecture"
---

# RFC: Replace asya-gateway with asya-mesh-api + Protocol Adapters

## 1. Motivation

`asya-gateway` is a ~7,150 LOC Go monolith that conflates five responsibilities:
external surface (auth, TLS), protocol translation (HTTP <-> MQ), metadata
serving, mesh sidecar callbacks, and SSE streaming. The api/mesh deployment
split requires `pg_notify` for cross-process sync, which has known problems
(8KB limit, dedicated PG connection, feedback loops, lost updates on pod restart).

**Root cause**: the split put SSE server and mesh receiver in different pods,
forcing a database-based pub/sub hack. The fix: keep SSE and mesh callbacks
in the same process, extract protocol adapters, use the message transport for
what it's designed for.

## 2. Design Principles

1. **/mesh/ is the universal API** -- protocol-agnostic, any client can use it
2. **The message knows the way** -- flow topology is in actors (yield SET), not
   in the gateway configuration
3. **asya-mesh-api has zero protocol knowledge** -- no MCP, no A2A, no flow
   registry. It only knows envelopes, executions, and events.
4. **Protocol adapters are optional sidecars** -- MCP and A2A adapters are
   separate binaries that translate their protocol to /mesh/ HTTP calls.
5. **DB is a document store** -- PG state-proxy connector with JSONB, no
   typed schema, no Alembic, expression indexes from env vars.
6. **Two-step API** -- separate "create message" from "subscribe to events"
   for consistent hash routing.
7. **Auth/LB via nginx Ingress** -- annotations for JWT, rate limiting,
   consistent hash. No custom auth code. agentgateway optional in Phase 2.

## 3. Architecture

### 3.1 Component Overview

```
nginx Ingress (auth, TLS, rate limit, consistent hash by URI-extracted envelope ID)
+---------------------------------------------------------------------------+
| /api/v1/mesh/*  --> asya-mesh-api :8080  (external mesh API)              |
| /mcp/*          --> asya-mcp-adapter :8082 (MCP Streamable HTTP)          |
| /a2a/*          --> asya-a2a-adapter :8083 (A2A JSON-RPC)                 |
| (internal)      --> asya-mesh-api :8081  (sidecar callbacks)              |
+---------------------------------------------------------------------------+

Single Deployment (one pod, three containers + state-proxy-pg sidecar):
+-----------------------------------------------------------------------+
|                                                                       |
|  asya-mesh-api (:8080 ext, :8081 int)              ~1,000-1,500 LOC   |
|    POST /api/v1/mesh/?actor=foo     create message, dispatch to MQ    |
|    GET  /api/v1/mesh/{id}           message status (from DB)          |
|    GET  /api/v1/mesh/{id}/events    subscribe (SSE)                   |
|    POST /api/v1/mesh/{id}/events    publish event (sidecar)           |
|    DELETE /api/v1/mesh/{id}         cancel                            |
|    GET  /api/v1/mesh/               list (filter by status, etc.)     |
|                                                                       |
|  asya-mcp-adapter (:8082)                          ~300-500 LOC       |
|    mark3labs/mcp-go library                                           |
|    tools/list from ConfigMap, tools/call -> mesh API                  |
|    Stateless, polls ConfigMap for hot-reload                          |
|                                                                       |
|  asya-a2a-adapter (:8083)                          ~500-800 LOC       |
|    a2aproject/a2a-go v2 library                                       |
|    tasks/send -> mesh API, tasks/subscribe -> mesh SSE                |
|    Agent card from ConfigMap, history from state-proxy                |
|    Stateless, polls ConfigMap for hot-reload                          |
|                                                                       |
|  state-proxy-pg (Unix socket)                      ~300-400 LOC       |
|    Go PG state-proxy connector (pgx driver)                           |
|    KV: read/write/list/delete on JSONB table                          |
|    /query endpoint: Mango-style filter -> SQL                         |
|    Expression indexes from env vars (self-configuring)                |
|                                                                       |
+-----------------------------------------------------------------------+
                         |
                   envelope -> MQ (SQS / PubSub / RabbitMQ / NATS)
                         |
                    Actor Mesh
```

### 3.2 API: /api/v1/mesh/

The mesh API manages one abstraction: **messages** (envelopes in flight).

**External (port 8080, authenticated via nginx Ingress):**

```
POST   /api/v1/mesh/?actor={name}     Create message, dispatch to actor queue
  Body: {"payload": {...}, "headers": {...}, "timeout": 300}
  Response: 201 {"id": "abc123"}

GET    /api/v1/mesh/{id}              Message status + metadata from DB
  Response: 200 {"id": "abc123", "status": "running", "data": {...}}

GET    /api/v1/mesh/{id}/events       Subscribe to SSE stream
  Response: 200 text/event-stream
  (Ingress extracts {id} from URI path for consistent hash routing)
  Events: status updates, FLY events, terminal status

DELETE /api/v1/mesh/{id}              Cancel message
  Response: 204

GET    /api/v1/mesh/                  List messages
  Query: ?status=running&limit=10&offset=0
  Response: 200 {"messages": [...], "total": 42}
```

**Internal (port 8081, NetworkPolicy: actor namespace pods only):**

```
POST   /api/v1/mesh/{id}/events      Publish event (sidecar status OR FLY)
  Body: {"type": "status", "status": "running", "data": {"actor": "x", "progress": 50}}
  (Ingress extracts {id} from URI path for consistent hash routing)
  Body: {"type": "fly", "data": {"text": "token..."}}
  Body: {"type": "status", "status": "succeeded", "data": {"actor": "x-sink"}}
  Response: 204

GET    /api/v1/mesh/{id}              Check if message is active (sidecar heartbeat)
  Sidecar checks response status field. If canceled/paused -> stop processing.
  Response: 200 {"id": "abc123", "status": "running", "data": {...}}
  (same endpoint as external GET, different port for security)
```

**Unified /events endpoint**: GET subscribes (SSE), POST publishes (sidecar).
Producer and consumer on the same resource path, different HTTP methods.
Event types differentiated by `type` field in POST body (status, fly).
Status updates and terminal events merged into one POST (no separate /progress
and /final endpoints).

### 3.3 Two-Step Dispatch

Task creation and event subscription are separate HTTP requests:

1. `POST /api/v1/mesh/?actor=foo` -- round-robin (any pod generates ID)
2. `GET /api/v1/mesh/{id}/events` -- hash-routed (consistent pod holds SSE)

Why: the ID exists before the hash-routed request, solving the chicken-and-egg.
Matches A2A spec (`tasks/send` + `tasks/subscribe`).

MCP adapter combines both into a single MCP Streamable HTTP response:
1. Receives tools/call
2. POST to mesh API (gets ID)
3. GET /mesh/{id}/events via Ingress (hash-routed, gets SSE)
4. Translates mesh SSE events -> MCP progress notifications + final result

### 3.4 Envelope Header: x-asya-gateway-url

The dispatcher stamps the Internal Ingress URL into the envelope:

```json
{
  "id": "abc123",
  "route": {"curr": "start-my-flow", "prev": [], "next": []},
  "headers": {"x-asya-gateway-url": "http://asya-mesh-api-int.asya-system"},
  "payload": {"lr": 0.001}
}
```

Sidecar reads the URL from the envelope for all callbacks. Falls back to
ASYA_GATEWAY_URL env var for backward compatibility.

**Eliminates ASYA_GATEWAY_URL env var** from Crossplane composition. Actors
fully decoupled from gateway topology.

### 3.5 Sidecar Changes

```go
// 1. Read gateway URL from envelope (not env var)
gatewayURL := envelope.Headers["x-asya-gateway-url"]
if gatewayURL == "" {
    gatewayURL = os.Getenv("ASYA_GATEWAY_URL") // backward compat
}

// 2. Unified event POST (replaces separate progress/final/fly POSTs)
req, _ := http.NewRequest("POST", gatewayURL+"/api/v1/mesh/"+id+"/events", body)
// No custom header needed — Ingress extracts ID from URI path

// 3. Check if still active (replaces /mesh/{id}/active)
resp := http.Get(gatewayURL+"/api/v1/mesh/"+id)
if resp.Status == "canceled" || resp.Status == "paused" { stop() }
```

### 3.6 Consistent Hash Routing

The envelope ID is already in the URL path (`/api/v1/mesh/{id}/...`). nginx
extracts it with a `map` directive — no custom HTTP header needed.

Two nginx Ingresses, both hash by URI-extracted envelope ID:

**External Ingress:**
```yaml
# Task creation: round-robin (no ID yet)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: asya-mesh-api-create
spec:
  rules:
  - http:
      paths:
      - path: /api/v1/mesh/
        pathType: Exact
        backend:
          service: {name: asya-mesh-api, port: {number: 8080}}
---
# All ID-bearing requests: consistent hash
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: asya-mesh-api-sticky
  annotations:
    nginx.ingress.kubernetes.io/server-snippet: |
      map $uri $envelope_id {
        ~^/api/v1/mesh/([^/]+) $1;
        default "";
      }
    nginx.ingress.kubernetes.io/upstream-hash-by: "$envelope_id"
spec:
  rules:
  - http:
      paths:
      - path: /api/v1/mesh/
        pathType: Prefix
        backend:
          service: {name: asya-mesh-api, port: {number: 8080}}
      - path: /mcp/
        pathType: Prefix
        backend:
          service: {name: asya-mesh-api, port: {number: 8082}}
      - path: /a2a/
        pathType: Prefix
        backend:
          service: {name: asya-mesh-api, port: {number: 8083}}
```

**Internal Ingress:**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: asya-mesh-api-internal
  annotations:
    nginx.ingress.kubernetes.io/server-snippet: |
      map $uri $envelope_id {
        ~^/api/v1/mesh/([^/]+) $1;
        default "";
      }
    nginx.ingress.kubernetes.io/upstream-hash-by: "$envelope_id"
spec:
  rules:
  - http:
      paths:
      - path: /api/v1/mesh/
        pathType: Prefix
        backend:
          service: {name: asya-mesh-api, port: {number: 8081}}
```

### 3.7 Security: Three Blast Radiuses

| Layer | What | Auth | NetworkPolicy |
|---|---|---|---|
| nginx Ingress | Internet-facing | JWT (annotation), rate limit | Allow from internet |
| External port 8080/8082/8083 | Behind Ingress | nginx JWT | Allow from Ingress pods |
| Internal port 8081 | Sidecar callbacks | None (network isolation) | Actor namespace pods only |

### 3.8 SSE Catch-Up on Reconnect

Between POST (create) and GET /events (subscribe), or after disconnect:

```go
func handleEventsGet(w http.ResponseWriter, r *http.Request) {
    id := chi.URLParam(r, "id")

    // Catch up from DB
    msg := store.Get(id)
    if isTerminal(msg.Status) {
        writeSSE(w, msg) // already done
        return
    }

    // Subscribe for live events (in-process Go channel)
    ch := subscribers.Add(id)
    defer subscribers.Remove(id, ch)
    for event := range ch {
        writeSSE(w, event)
        if isTerminal(event.Status) { return }
    }
}
```

### 3.9 Pod Failure

```
Pod A holds SSE for "abc123". Pod A dies.
1. SSE drops (TCP reset)
2. Client reconnects: GET /api/v1/mesh/abc123/events
3. Ingress extracts "abc123" from URI, hash ring rebalanced: -> Pod B
4. Pod B catches up from DB, subscribes
5. Sidecar next POST: /api/v1/mesh/abc123/events -> Ingress extracts ID -> Pod B (same hash)
6. Both sides converge on Pod B
```

## 4. Protocol Adapters

### 4.1 MCP and A2A Are Siblings

Neither is a subset of the other. Both are adapters over /mesh/.

| | MCP | A2A |
|---|---|---|
| Model | Function call (structured params -> result) | Conversation (messages, history, pause/resume) |
| Discovery | tools/list with JSON Schema | Agent card with skills |
| Streaming | Progress notifications (% + text only) | Artifact stream (rich content, FLY events) |
| State | Stateless per call | Task state machine (9 states) |
| Use case | Training pipeline, deployment, queries | Research orchestrator, iterative agent |

A flow declares ONE protocol. Not both.

### 4.2 MCP Adapter (~300-500 LOC)

Library: `mark3labs/mcp-go`

Speaks MCP Streamable HTTP to clients (or agentgateway in Phase 2).
Reads tool definitions from ConfigMap (`/etc/asya/mcp/`).
Translates tools/call to mesh API calls.

```
tools/list -> return tool definitions from ConfigMap
tools/call "train_model" {lr: 0.001} ->
  1. POST /api/v1/mesh/?actor=start-my-flow (local, same pod)
     -> gets {id: "abc123"}
  2. GET /api/v1/mesh/abc123/events via Ingress (hash-routed)
     -> SSE stream
  3. Translate mesh events -> MCP events:
     status event -> notifications/progress (% + message text)
     fly event    -> notifications/message (log with data field)
     terminal     -> CallToolResult (final response)
  4. Return as text/event-stream (MCP Streamable HTTP)
```

**ConfigMap schema** (`asya-mcp-tools`):
```yaml
tools:
  - name: train_model
    description: "Train a model with given hyperparameters"
    actor: start-my-flow
    timeout: 3600
    inputSchema:
      type: object
      properties:
        lr: {type: number}
        epochs: {type: integer}
      required: [lr]
    progress: true
```

### 4.3 A2A Adapter (~500-800 LOC)

Library: `a2aproject/a2a-go` v2

Speaks A2A JSON-RPC to clients (or agentgateway passthrough in Phase 2).
Reads agent definitions from ConfigMap (`/etc/asya/a2a/`).
Translates A2A methods to mesh API calls.

| A2A method | Mesh API call |
|---|---|
| tasks/send | POST /api/v1/mesh/?actor={actor} |
| tasks/subscribe | GET /api/v1/mesh/{id}/events via Ingress |
| tasks/sendSubscribe | Both combined |
| tasks/get | GET /api/v1/mesh/{id} + state-proxy for history |
| tasks/cancel | DELETE /api/v1/mesh/{id} |
| GetExtendedAgentCard | Serve from ConfigMap |

**State mapping** (envelope.id = task_id, context_id = contextId):

| Mesh status | A2A TaskState |
|---|---|
| pending | submitted |
| running | working |
| succeeded | completed |
| failed | failed |
| paused | input_required |
| canceled | canceled |

**History hydration**: A2A tasks/get needs conversation history. This lives
in state-proxy (x-sink persists full envelope payload to S3). The a2a-adapter
pod has a state-proxy-s3 sidecar that reads history via Unix socket:
`GET /keys/{task_id}` -> returns persisted envelope with `payload.a2a.task.history`.
History is a SHOULD in the A2A spec -- happy path is stateless.

**ConfigMap schema** (`asya-a2a-agents`):
```yaml
agents:
  - name: autoresearch
    description: "Autonomous ML experimentation agent"
    actor: start-autoresearch
    timeout: 14400
    streaming: true
    skills:
      - id: experiment
        name: Run experiment
        description: "Execute training experiments"
        tags: [ml, training]
    inputModes: [text/plain, application/json]
    outputModes: [text/plain, application/json]
```

### 4.4 Hot-Reload

Both adapters use the same polling watcher pattern (~30 LOC, shared Go code
from the existing toolstore.Watch implementation):

```
asya expose --as mcp -> kubectl create/patch ConfigMap
-> Kubelet syncs ConfigMap to mounted volume (~10s)
-> Adapter polling watcher detects file change (10s interval, fingerprint)
-> Adapter reloads tool/agent registry (atomic cache swap)
-> Next MCP tools/list or A2A agent card reflects the change
```

No fsnotify needed. Reuse existing polling watcher code.

## 5. Storage: PG State-Proxy Connector

### 5.1 Document Store Interface

The mesh-api talks to its DB through the state-proxy HTTP interface over
Unix socket. No SQL in the mesh-api Go code. No PG driver dependency.

```
mesh-api -> HTTP/Unix socket -> state-proxy-pg -> PostgreSQL
```

State-proxy interface (existing + /query extension):
```
GET    /keys/{key}          Read document
PUT    /keys/{key}          Write document (upsert)
HEAD   /keys/{key}          Check existence
DELETE /keys/{key}          Delete document
GET    /keys/?prefix=X      List keys by prefix
POST   /query               Structured query (filter/sort/limit)
```

### 5.2 PG Schema (One Table, Never Changes)

```sql
CREATE TABLE IF NOT EXISTS kv (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fallback GIN for ad-hoc JSONB queries
CREATE INDEX IF NOT EXISTS idx_kv_gin ON kv USING gin (value jsonb_path_ops);
```

**4 columns. No Alembic. No migrations. Ever.**

A mesh message stored as:
```
key:   "msg/abc123"
value: {
  "status": "running",
  "actor": "train-model",
  "progress": 50.0,
  "context_id": "session-42",
  "trace_id": "abc",
  "parent_id": "parent-456",
  "deadline_at": "2026-04-16T12:00:00Z",
  "error": null,
  "message": "Step 500/1000"
}
```

All fields in JSONB. No typed columns. context_id, parent_id, trace_id are
application concerns -- they live in data, not in schema.

### 5.3 Expression Indexes (Self-Configuring from Env Vars)

```bash
# Helm values / deployment env
STATE_PROXY_PG_INDEXES: "status, (deadline_at)::timestamptz"
```

On startup, the connector runs (lock-free, safe on live tables):
```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kv_expr_status
    ON kv ((value->>'status'));
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_kv_expr_deadline
    ON kv (((value->>'deadline_at')::timestamptz));
```

Add new indexes by changing an env var and restarting. No schema migration.
No table locks. Expression indexes give B-tree performance on JSONB fields.

### 5.4 Query Endpoint (/query)

Mango-style filter DSL (not GraphQL -- simpler, covers 95% of cases):

```json
POST /query
{
  "prefix": "msg/",
  "filter": {
    "status": "running",
    "progress": {"$gt": 50},
    "context_id": "session-42"
  },
  "sort": ["-created_at"],
  "limit": 10,
  "offset": 0
}
```

Translates to parameterized SQL:
```sql
SELECT key, value, created_at, updated_at FROM kv
WHERE key LIKE 'msg/%'
  AND value @> '{"status": "running"}'
  AND (value->>'progress')::numeric > 50
  AND value @> '{"context_id": "session-42"}'
ORDER BY created_at DESC
LIMIT 10 OFFSET 0
```

Operators: $eq (implicit), $ne, $gt/$gte/$lt/$lte, $in, $nin, $contains,
$exists. Input validated, parameterized (no SQL injection).

### 5.5 Go MessageStore Interface

The mesh-api's internal interface for DB access. Implemented by calling the
state-proxy HTTP API over Unix socket.

```go
type MessageStore interface {
    Create(ctx context.Context, id, actor string, payload, headers json.RawMessage, timeout int) error
    Get(ctx context.Context, id string) (*Message, error)
    UpdateStatus(ctx context.Context, id string, status string, data json.RawMessage) error
    Delete(ctx context.Context, id string) error
    List(ctx context.Context, params ListParams) ([]*Message, int, error)
    FindExpired(ctx context.Context) ([]string, error)

    // In-process (ephemeral, not persisted)
    Subscribe(ctx context.Context, id string) <-chan Event
    Unsubscribe(id string, ch <-chan Event)
    NotifyEvent(id string, event Event)
}

type Message struct {
    ID        string          `json:"id"`
    Status    string          `json:"status"`
    Data      json.RawMessage `json:"data"`       // all fields in JSONB
    CreatedAt time.Time       `json:"created_at"`
    UpdatedAt time.Time       `json:"updated_at"`
}

type ListParams struct {
    Filters map[string]any `json:"filter,omitempty"` // Mango-style
    Sort    []string       `json:"sort,omitempty"`   // ["-created_at"]
    Limit   int            `json:"limit,omitempty"`
    Offset  int            `json:"offset,omitempty"`
}
```

Create/Get/UpdateStatus/Delete map to state-proxy PUT/GET/PUT/DELETE on
key "msg/{id}". List and FindExpired map to POST /query.

Subscribe/Unsubscribe/NotifyEvent are in-process Go channels (not persisted,
not proxied). They connect the sidecar POST /events to the client GET /events.

### 5.6 Deployment Modes

```
Mode 1: Sidecar (standard Asya deployment)
  mesh-api -> HTTP/Unix socket -> state-proxy-pg sidecar -> PG
  Overhead: ~0.05ms/call. Universal. Swappable backends.

Mode 2: In-process library (low-latency, financial workloads)
  mesh-api -> Go function call -> pgx -> PG
  Overhead: 0. Same MessageStore interface. Different constructor.

Mode 3: In-memory (testing, development)
  mesh-api -> Go map (no DB)
  Overhead: 0. Same interface.
```

All three implement the same `MessageStore` interface. The mesh-api doesn't
know which mode it's using.

### 5.7 Connector Implementation (~300-400 LOC Go)

```go
// state-proxy-pg: Go PostgreSQL connector
// Implements StateProxyConnector interface over pgx

// KV operations:
//   read(key)    -> SELECT value FROM kv WHERE key = $1
//   write(key,v) -> INSERT INTO kv (key, value) ON CONFLICT DO UPDATE
//   list(prefix) -> SELECT key FROM kv WHERE key LIKE $1%
//   delete(key)  -> DELETE FROM kv WHERE key = $1

// Query endpoint:
//   query(filter, sort, limit, offset) -> filter-to-SQL translator
//   Operators: $eq, $ne, $gt, $gte, $lt, $lte, $in, $nin, $contains, $exists
//   Parameterized SQL (no injection)

// On startup:
//   1. CREATE TABLE IF NOT EXISTS kv (key, value, created_at, updated_at)
//   2. CREATE INDEX IF NOT EXISTS idx_kv_gin ON kv USING gin (value jsonb_path_ops)
//   3. Read STATE_PROXY_PG_INDEXES env var
//   4. CREATE INDEX CONCURRENTLY IF NOT EXISTS for each configured field
```

## 6. Package Structure

One Go module, three binaries:

```
src/asya-gateway/
  cmd/
    mesh-api/         main.go  -> asya-mesh-api binary
    mcp-adapter/      main.go  -> asya-mcp-adapter binary
    a2a-adapter/      main.go  -> asya-a2a-adapter binary
  internal/
    mesh/             Core mesh API handlers (create, get, events, cancel, list)
    mcp/              MCP Streamable HTTP handler (mark3labs/mcp-go)
    a2a/              A2A JSON-RPC handler (a2aproject/a2a-go v2)
    store/            MessageStore interface + HTTP state-proxy client
    watcher/          ConfigMap polling watcher (shared, ~30 LOC)
  pkg/
    types/            Shared types (Message, Event, etc.)
  go.mod
```

## 7. Flow Topology

**The message knows the way.** Flow topology lives in actors (yield SET),
not in the gateway/dispatcher.

```
POST /api/v1/mesh/?actor=start-my-flow
  Body: {"payload": {"lr": 0.001}, "headers": {}}

Dispatcher creates envelope:
  id: "abc123"
  route: {prev: [], curr: "start-my-flow", next: []}
  headers: {x-asya-gateway-url: "http://..."}
  payload: {lr: 0.001}

Dispatches to "start-my-flow" queue. The start router actor:
  yield "SET", ".route.next", ["train-actor", "eval-actor"]
  yield payload

The mesh self-organizes. Dispatcher knows nothing about the graph.
```

For simple single-actor use (no flow): POST to that actor directly.
For compiled flows: POST to the start router (which sets route.next).

## 8. Exposure Mechanism

`asya expose` creates ConfigMaps that adapters hot-reload:

```bash
# Expose flow as MCP tool
asya expose start-my-flow --as mcp \
  --name train_model \
  --description "Train a model" \
  --schema '{"type":"object","properties":{"lr":{"type":"number"}}}'
# -> kubectl create/patch configmap asya-mcp-tools

# Expose flow as A2A agent
asya expose start-autoresearch --as a2a \
  --name autoresearch \
  --description "Autonomous ML agent" \
  --streaming
# -> kubectl create/patch configmap asya-a2a-agents
```

The mesh-api knows nothing about these exposures. Only the adapters read them.

**Phase 2**: Add agentgateway in front of the MCP adapter for tool federation
(aggregate tools from multiple meshes + external MCP servers). The MCP adapter
becomes an MCP upstream for agentgateway. No adapter code changes.

## 9. Code Impact

| Current component | LOC | Fate |
|---|---|---|
| internal/mcp/ (MCP server) | ~1,868 | Delete -> mcp-adapter (~300-500 LOC) |
| internal/envelopestore/ (PG + pg_notify) | ~1,593 | Delete -> state-proxy-pg (~300-400 LOC) |
| internal/a2a/ (A2A server) | ~1,381 | Simplify -> a2a-adapter (~500-800 LOC) |
| internal/queue/ (MQ clients) | ~1,332 | Simplify -> mesh-api queue publish (~400 LOC) |
| internal/mcp/handlers.go (mesh) | ~759 | Simplify -> mesh handlers (~300 LOC) |
| internal/oauth/ | ~521 | Delete (nginx Ingress auth) |
| internal/toolstore/ | ~515 | Delete -> adapter ConfigMaps |
| internal/consumer/ | ~196 | Delete (status via sidecar POST) |
| internal/tracing/ | ~79 | Simplify (~30 LOC) |
| **Total current** | **~7,150** | |
| **Total new** | | **~2,500-3,500 LOC** (mesh + adapters + connector) |

~50-65% code reduction. Remaining code is simpler (no pg_notify, no auth,
no MCP/A2A in core, no flow registry).

## 10. Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| State-proxy sidecar crash | Low | K8s auto-restarts container (not pod). Liveness probe. |
| HTTP-over-Unix latency (+0.05ms) | Low | Negligible vs MQ/actor latency. In-process mode for low-latency. |
| JSONB storage overhead (~2x vs typed) | Low | ~100 bytes/row. Expression indexes for query speed. |
| Timing gap create->subscribe | Low | DB catch-up on reconnect (standard pattern) |
| nginx Ingress required | Low | Standard in most clusters |
| Sidecar backward compat | Low | Fall back to env var if header missing |
| No MCP federation initially | Low | Phase 2: add agentgateway as MCP aggregation layer |
| Mango query DSL limitations | Low | Covers 95% of cases. Extend if needed. |

## 11. Open Questions

1. Should the PG state-proxy connector be Go or Python? Go preferred (same
   toolchain, pgx driver, can be compiled as library for low-latency mode).
2. Pause/resume: same message row updated (status: paused->running). How does
   the a2a-adapter handle resume dispatching to x-resume queue?
3. Dashboard: reads /api/v1/mesh/ directly. Embedded Grafana for traces/metrics.
   Separate aint for dashboard design.
4. Event log for SSE replay: should we store events in a message_events table
   (via state-proxy), or is catch-up from current status sufficient?
5. MCP Tasks (experimental spec 2025-11-25): monitor and consider adopting
   when stable. Would replace the two-step pattern for MCP.
