---
title: "RFC: agentgateway + asya-dispatcher Architecture"
---

# RFC: Replace asya-gateway with agentgateway + asya-dispatcher

## 1. Motivation

`asya-gateway` is a ~7,150 LOC Go monolith that conflates five responsibilities:

1. **External surface** (auth, TLS, rate limiting, protocol endpoints)
2. **Protocol translation** (HTTP -> envelope -> MQ)
3. **Metadata serving** (task status, progress for external clients)
4. **Mesh receiver** (sidecar status/FLY callbacks)
5. **SSE streaming** (real-time events to clients)

The api/mesh deployment split (separate pods for (1,2,3,5) vs (4)) requires
`pg_notify` for cross-process sync. `pg_notify` has known problems:

- 8KB payload limit (FLY events regularly exceed this)
- Dedicated PG connection required (not from pool), manual reconnect
- Feedback loop risk (Save -> Update -> notifyListeners -> channel -> Save)
- 2-second DB poll fallback for oversized events
- Lost status updates when mesh gateway pod restarts during sidecar HTTP POST

**Root cause**: the api/mesh split put the SSE server and mesh receiver in
different pods, forcing a database-based pub/sub hack. The fix is architectural:
keep SSE and mesh callbacks in the same process.

## 2. Design Principles

1. **/mesh/ is the universal API** -- Asya-native, protocol-agnostic. Any
   client (dashboard, CLI, coding agent) can use /mesh/ directly. MCP and A2A
   are optional protocol adapters on top.
2. **ID generation is application concern** -- dispatcher generates envelope
   IDs, not the networking layer.
3. **Routing is networking concern** -- Ingress routes by consistent hash.
4. **DB stores metadata only** -- not used as pub/sub bus.
5. **SSE and mesh callbacks colocate** -- same process, Go channels.
6. **Two-step API** -- separate "create task" from "subscribe to events."
7. **MCP and A2A are siblings, not layers** -- different protocols for
   different interaction patterns, both built on /mesh/.

## 3. Architecture

### 3.1 Component Overview

```
Internet
  |
  +-- MCP clients --> agentgateway (Rust) --> dispatcher :8080 /mesh/*
  |                   MCP server                (tool call -> POST /mesh/
  |                   Auth, RBAC, federation      subscribe -> GET /mesh/{id}/stream)
  |
  +-- A2A clients --> agentgateway (proxy) --> dispatcher :8080 /a2a/*
  |                   Auth, rate limit,          A2A adapter over /mesh/
  |                   observability               (task lifecycle, history,
  |                   (common proxy features)      pause/resume)
  |
  +-- Dashboard ----> External Ingress -----> dispatcher :8080 /mesh/*
                      Session auth              Direct /mesh/ access
                                                (list, status, SSE)

Cluster-internal
  |
  +-- Sidecars -----> Internal Ingress -----> dispatcher :8081 /mesh/{id}/*
                      NetworkPolicy only        (progress, final, fly)
                      Hash by X-Asya-Envelope-ID
```

### 3.2 /mesh/ -- Universal Asya API

All external protocols are adapters over /mesh/. /mesh/ is the core API.

```
               /mesh/{id}                    <-- Asya native (universal)
              /          \
          /mcp/         /a2a/                <-- Protocol adapters
      (agentgateway)  (dispatcher)

Neither is a subset of the other.
Both translate to /mesh/ calls.
```

**Port 8080 (external, authenticated):**

| Endpoint | Method | Purpose | Routing |
|---|---|---|---|
| `/mesh/` | POST | Create task, dispatch to MQ | Round-robin |
| `/mesh/{id}` | GET | Task status + metadata | Hash-routed |
| `/mesh/{id}/stream` | GET | SSE: FLY events + status | Hash-routed |
| `/mesh/{id}` | DELETE | Cancel task | Hash-routed |
| `/mesh/?context_id=X` | GET | List tasks (dashboard) | Any pod |
| `/a2a/*` | POST | A2A JSON-RPC adapter | Hash-routed |

**Port 8081 (internal, NetworkPolicy-protected):**

| Endpoint | Method | Purpose | Routing |
|---|---|---|---|
| `/mesh/{id}/progress` | POST | Sidecar progress update | Hash-routed |
| `/mesh/{id}/final` | POST | Sidecar terminal status | Hash-routed |
| `/mesh/{id}/fly` | POST | Sidecar FLY event | Hash-routed |
| `/mesh/{id}/active` | GET | Sidecar heartbeat check | Hash-routed |
| `/mesh/` | POST | Fanout child creation | Hash-routed |

### 3.3 Two-Step API Pattern

Task creation and event subscription are separate HTTP requests. Standard REST
(POST creates, GET observes). Maps to A2A (`tasks/send` + `tasks/subscribe`)
and MCP (agentgateway combines both into single response).

**Step 1: Create task** (round-robin, any pod)
```
POST /mesh/
Request:  {flow: "train_model", params: {lr: 0.001, epochs: 50}}
Response: 201 {id: "abc123", stream_url: "/mesh/abc123/stream"}

Dispatcher generates envelope ID, dispatches to MQ.
No SSE held. Stateless. Any pod can handle this.
```

**Step 2: Subscribe to events** (hash-routed to consistent pod)
```
GET /mesh/abc123/stream
Header:   X-Asya-Envelope-ID: abc123
Response: SSE stream (progress, FLY events, terminal status)

Ingress hashes "abc123" -> routes to Pod A.
Pod A subscribes in-memory, holds SSE connection.
```

**Sidecar callbacks** (hash-routed to same pod)
```
POST /mesh/abc123/fly
Header:   X-Asya-Envelope-ID: abc123
Body:     {"text": "token chunk..."}

Internal Ingress hashes "abc123" -> Pod A (same pod).
Pod A delivers via Go channel -> SSE -> client.
```

**Why two steps:**
- Creation is stateless (round-robin) -- any pod can generate an ID
- Subscription is stateful (hash-routed) -- must colocate with sidecar callbacks
- The ID exists before the hash-routed request (solves chicken-and-egg)
- Idempotent: `/mesh/{id}/stream` retryable on disconnect without re-creating
- Matches A2A spec (`tasks/send` + `tasks/subscribe`)
- agentgateway combines both for MCP (transparent to MCP clients)

### 3.4 Envelope Header: `x-asya-gateway-url`

The envelope carries the dispatcher's Internal Ingress URL:

```json
{
  "id": "abc123",
  "headers": {
    "x-asya-gateway-url": "http://asya-dispatcher-mesh.asya-system"
  },
  "route": {"prev": [], "curr": "actor-a", "next": ["actor-b"]},
  "payload": {...}
}
```

Sidecar reads this from the envelope. **Eliminates `ASYA_GATEWAY_URL` env var.**
Actors decoupled from gateway topology. URL set at dispatch time.

### 3.5 Consistent Hash Routing via Ingress

**External Ingress** (client-facing):
```yaml
# Task creation: round-robin (no ID yet)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: asya-dispatcher-create
spec:
  rules:
  - http:
      paths:
      - path: /mesh/
        pathType: Exact
        backend:
          service: {name: asya-dispatcher, port: {number: 8080}}
---
# All ID-bearing requests: consistent hash
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: asya-dispatcher-sticky
  annotations:
    nginx.ingress.kubernetes.io/upstream-hash-by: "$http_x_asya_envelope_id"
spec:
  rules:
  - http:
      paths:
      - path: /mesh/
        pathType: Prefix
        backend:
          service: {name: asya-dispatcher, port: {number: 8080}}
      - path: /a2a/
        pathType: Prefix
        backend:
          service: {name: asya-dispatcher, port: {number: 8080}}
```

**Internal Ingress** (sidecar-facing):
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: asya-dispatcher-mesh
  annotations:
    nginx.ingress.kubernetes.io/upstream-hash-by: "$http_x_asya_envelope_id"
spec:
  rules:
  - http:
      paths:
      - path: /mesh/
        pathType: Prefix
        backend:
          service: {name: asya-dispatcher, port: {number: 8081}}
```

### 3.6 SSE Catch-Up on Reconnect

Between POST /mesh/ and GET /mesh/{id}/stream, or after disconnect, events
may be missed. Standard catch-up from DB on subscribe:

```go
func handleStream(w http.ResponseWriter, r *http.Request) {
    id := chi.URLParam(r, "id")

    task := db.Get(id)
    if task.IsTerminal() {
        writeSSEEvent(w, task.FinalStatus)
        return
    }

    ch := subscribers.Add(id)
    defer subscribers.Remove(id, ch)

    for event := range ch {
        writeSSEEvent(w, event)
        if event.IsTerminal() {
            return
        }
    }
}
```

### 3.7 Security Model (Three Blast Radiuses)

| Layer | What | Auth | NetworkPolicy |
|---|---|---|---|
| agentgateway | Internet-facing (MCP, A2A auth) | JWT/OIDC, CEL RBAC, rate limiting | Allow from internet |
| External Ingress | Cluster-internal (dispatcher :8080) | agentgateway auth or session auth | Allow from agentgateway + dashboard pods |
| Internal Ingress | Cluster-internal (dispatcher :8081) | None (network isolation) | Allow from actor namespace pods only |

### 3.8 Pod Failure Handling

```
Pod A holds SSE for "abc123", Pod A is OOMKilled:
1. SSE drops (TCP reset)
2. Client reconnects: GET /mesh/abc123/stream (X-Asya-Envelope-ID: abc123)
3. Ketama hash ring rebalances: abc123 -> Pod B
4. Pod B catches up from DB, subscribes for live events
5. Sidecar next POST: X-Asya-Envelope-ID: abc123 -> Ingress -> Pod B
6. Both sides converge on Pod B automatically
```

## 4. MCP and A2A Protocol Placement

### 4.1 They Are Siblings, Not Layers

| | MCP | A2A |
|---|---|---|
| Mental model | Function call | Conversation |
| Input | Structured params (JSON Schema) | Natural language message |
| Output | Structured result | Messages (may ask questions first) |
| Progress | % + status text (no structured data) | Rich content stream (reasoning, tokens) |
| State | Stateless per call (Tasks experimental) | Stateful task (history accumulates) |
| Pause/resume | No (experimental Tasks add this) | Yes (`input_required`) |
| Who drives | Caller drives | Agent drives (may push back) |
| Discovery | `tools/list` with schemas | Agent card with skills |

MCP has things A2A doesn't: tool schemas, resources, prompts, sampling.
A2A has things MCP doesn't: task state machine, conversation history,
push notifications.

### 4.2 Which Protocol for What

| Interaction pattern | Protocol | Examples |
|---|---|---|
| "Execute X with params, report progress" | MCP (or /mesh/ direct) | Training pipeline, deployment, metrics query |
| "Work on this problem, ask me if stuck" | A2A | Research orchestrator, iterative agent |
| "Show me live updates for task X" | /mesh/{id}/stream (SSE) | Dashboard, CLI monitoring |

**A flow declares ONE protocol.** Not both. The protocol determines how the
flow is discovered and invoked.

### 4.3 MCP via agentgateway

agentgateway implements a real MCP server with tool federation:
- `tools/list` -> aggregates tools from dispatcher + external MCP servers
- `tools/call` -> `POST /mesh/` + `GET /mesh/{id}/stream`
- Progress: maps FLY events to MCP progress notifications (% + message text)
- Auth: JWT/OIDC, CEL-based per-tool RBAC
- Sessions: encrypted cookies, stateful/stateless modes

### 4.4 A2A via Dispatcher

The dispatcher implements the A2A server (adapter over /mesh/):
- `tasks/send` -> `POST /mesh/` (with A2A payload mapping)
- `tasks/subscribe` -> `GET /mesh/{id}/stream` (FLY -> artifact stream)
- `tasks/get` -> `GET /mesh/{id}` + state-proxy for history
- `tasks/sendSubscribe` -> both steps combined
- `tasks/cancel` -> `DELETE /mesh/{id}`
- `input_required` <- x-pause status from mesh
- Agent card served at `/.well-known/agent.json`

A2A requests route through agentgateway for common proxy features (auth,
rate limiting, observability) but A2A protocol logic lives in the dispatcher.

### 4.5 Dashboard via /mesh/ Direct

Dashboard uses /mesh/ directly -- no MCP, no A2A. Just REST + SSE:
- `GET /mesh/?context_id=exp-42&status=running` -- list tasks
- `GET /mesh/{id}` -- task detail
- `GET /mesh/{id}/stream` -- live FLY events (loss curves, reasoning)
- Also reads from: Loki (logs), Grafana (metrics/traces) -- no K8s auth needed

## 5. agentgateway Integration

### 5.1 What agentgateway Provides (MCP Only)

- MCP tool federation (aggregate from multiple Asya meshes + external servers)
- Per-tool RBAC via CEL expressions
- Token-bucket + global rate limiting
- Content guardrails (regex, OpenAI moderation, Bedrock, Model Armor)
- OpenAPI-to-MCP auto-conversion
- Built-in admin UI + MCP playground
- Full OTLP observability
- MCP auth spec compliance (OIDC, Keycloak, Auth0)
- Session management

### 5.2 What agentgateway Does NOT Help With

- A2A server (pure passthrough, empty policy struct, ~100 LOC Rust)
- A2A agent card aggregation (no federation, 1:1 proxy)
- A2A RBAC (no CEL for A2A)
- Task state management (stateless proxy)

### 5.3 Config Example

```yaml
binds:
- port: 443
  tls: {cert: ..., key: ...}
  listeners:
  - routes:
    # MCP: agentgateway is the server, deep support
    - policies:
        mcp:
          failMode: failClosed
        authentication:
          jwt: {jwksUrl: "https://...", issuer: "..."}
        mcpAuthorization:
          rules:
          - 'jwt.role == "admin"'
          - 'jwt.team == "ml" && mcp.tool.name.startsWith("training_")'
        rateLimit:
          local: {maxTokens: 100, tokensPerFill: 10, fillInterval: 1s}
      backends:
      - host: asya-dispatcher-ext
        mcp:
          transport: streamablehttp

    # A2A: passthrough, auth only
    - policies:
        a2a: {}
        authentication:
          jwt: {jwksUrl: "https://..."}
      backends:
      - host: asya-dispatcher-ext
```

## 6. Sidecar Changes

### 6.1 Read Gateway URL from Envelope

```go
// Before: hardcoded at deploy time
gatewayURL := os.Getenv("ASYA_GATEWAY_URL")

// After: read from envelope header (fall back to env var for compat)
gatewayURL := envelope.Headers["x-asya-gateway-url"]
if gatewayURL == "" {
    gatewayURL = os.Getenv("ASYA_GATEWAY_URL")
}
```

### 6.2 Set X-Asya-Envelope-ID on Every POST

```go
req, _ := http.NewRequest("POST", gatewayURL+"/mesh/"+id+"/fly", body)
req.Header.Set("X-Asya-Envelope-ID", id)
```

Both changes are backward-compatible.

## 7. Database (Metadata Only)

```sql
CREATE TABLE tasks (
    id          TEXT PRIMARY KEY,
    parent_id   TEXT,
    context_id  TEXT,
    status      TEXT NOT NULL,
    actor       TEXT,
    progress    DECIMAL(5,2),
    created_at  TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ
);
CREATE INDEX idx_tasks_context ON tasks(context_id);
CREATE INDEX idx_tasks_status ON tasks(status);
```

No payload JSONB. No result JSONB. No task_updates table. No pg_notify.
Payload/result in state-proxy (S3/GCS). Writes are async fire-and-forget.
Reads for SSE catch-up and dashboard queries.

## 8. Code Impact

### 8.1 What Gets Deleted

| Component | LOC | Reason |
|---|---|---|
| internal/mcp/ (all) | ~1,868 | agentgateway replaces MCP |
| internal/envelopestore/ (all) | ~1,593 | Simplified DB, no pg_notify |
| internal/oauth/ (all) | ~521 | agentgateway handles auth |
| internal/toolstore/ (all) | ~515 | agentgateway discovers tools |
| internal/consumer/ | ~196 | No x-sink queue consumer |
| internal/a2a/auth.go | ~216 | agentgateway handles auth |
| internal/a2a/agent_card_producer.go | ~151 | Simplified agent card |

### 8.2 What Gets Simplified

| Component | Before | After |
|---|---|---|
| A2A executor | ~266 | ~150 (adapter over /mesh/) |
| A2A blocking wait | ~233 | ~80 (in-process subscribe) |
| A2A store adapter | ~312 | ~100 (read from state-proxy) |
| Queue integration | ~1,332 | ~400 (publish only) |
| Mesh handlers | ~759 | ~300 (deliver + async DB) |
| Main wiring | ~439 | ~150 |

### 8.3 Net Result

~7,150 -> ~2,000 LOC (72% reduction).

## 9. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Timing gap between dispatch and subscribe | Low | DB catch-up on subscribe |
| ListTasks without full SQL | Medium | Simple DB with context_id index |
| nginx Ingress required | Low | Standard in most clusters |
| Sidecar breaking change | Low | Backward-compat: fall back to env var |
| agentgateway maturity | Medium | MCP-only dependency; A2A stays in-house |
| A2A ecosystem gap | Info | No alternative exists; we build it |
| Pod death during SSE | Low | Reconnect + hash rebalance + DB catch-up |

## 10. Open Questions

1. Timeout enforcement: local timer per subscription? Pod restart mid-timeout?
2. Migration: can old gateway and new dispatcher run in parallel?
3. Should dispatcher expose a simple MCP server as fallback for
   non-agentgateway deployments?
4. Dashboard auth: session-based? Behind agentgateway? Separate?
5. MCP Tasks (experimental spec 2025-11-25): converging with A2A. Monitor
   and consider adopting when stable.
