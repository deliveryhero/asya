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

1. **ID generation is an application concern** -- the dispatcher generates
   envelope IDs, not the networking layer
2. **Routing is a networking concern** -- Ingress routes by consistent hash,
   application code doesn't know about pod topology
3. **DB stores metadata only** -- not used as a pub/sub bus
4. **SSE and mesh callbacks colocate** -- same process, Go channels, zero latency
5. **Sidecars report via HTTP** -- bypasses MQ latency for real-time streaming
6. **Two-step API** -- separate "create task" from "subscribe to events"

## 3. Architecture

### 3.1 Component Overview

```
Client
  |
  v
agentgateway (Rust, LF project)        <-- Responsibility 1: External surface
  MCP server (tool federation)              Auth, rate limiting, guardrails
  A2A passthrough proxy                     Observability
  |               |
  |  1. POST      |  2. GET /stream/{id}
  |  /dispatch    |  (X-Asya-Envelope-ID: abc123)
  |               |
  v               v
External Ingress                        <-- Networking layer
  /dispatch  -> round-robin (no hash)       Routing only, no ID generation
  /stream/*  -> hash by X-Asya-Envelope-ID
  /tasks/*   -> hash by X-Asya-Envelope-ID
  /a2a/*     -> hash by X-Asya-Envelope-ID
  |               |
  v               v
asya-dispatcher (Go, ~2,000 LOC)        <-- Responsibilities 2-5
  Port 8080: /dispatch, /stream, /tasks     Protocol translation
  Port 8081: /mesh/{id}/*                   SSE streaming
  |                                         Mesh callbacks (same process!)
  |                                         Metadata writes (async, DB)
  v
Internal Ingress                        <-- Networking layer
  /mesh/*  -> hash by X-Asya-Envelope-ID    (sidecar always sets header)
  ^
  |
Sidecars (actor pods)
  Read envelope ID + gateway URL from envelope headers
  Set X-Asya-Envelope-ID on every POST
```

### 3.2 Two-Step API Pattern

Task creation and event subscription are separate HTTP requests. This is
standard REST (POST creates, GET observes) and maps directly to A2A
(`tasks/send` + `tasks/subscribe`) and MCP (agentgateway combines both
into a single MCP tool response).

**Step 1: Create task** (round-robin, any pod)
```
POST /dispatch
Request:  {tool: "my_flow", params: {...}}
Response: 201 {id: "abc123", stream_url: "/stream/abc123"}

Dispatcher generates envelope ID, dispatches to MQ.
No SSE held. Stateless. Any pod can handle this.
```

**Step 2: Subscribe to events** (hash-routed to consistent pod)
```
GET /stream/abc123
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

Internal Ingress hashes "abc123" -> routes to Pod A (same pod!).
Pod A delivers via Go channel -> SSE -> client.
```

**Why two steps?**
- Creation is stateless (round-robin) -- any pod can generate an ID and
  dispatch to MQ. No routing problem.
- Subscription is stateful (hash-routed) -- the subscribing pod must be the
  same pod that receives sidecar callbacks. Consistent hash guarantees this.
- The ID exists before the hash-routed request, solving the chicken-and-egg.
- Idempotent observation: `/stream/{id}` can be retried on disconnect without
  re-creating the task.
- Matches A2A spec exactly (`tasks/send` + `tasks/subscribe`).
- agentgateway combines both steps into a single MCP tool response for
  MCP clients (transparent).

### 3.3 Envelope Header: `x-asya-gateway-url`

The envelope carries the dispatcher's Service URL in its headers:

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

The sidecar reads this URL from the envelope and uses it for all callbacks.

**This eliminates `ASYA_GATEWAY_URL` env var from sidecars.** Currently the
Crossplane composition injects this at deploy time, creating a coupling
between actor deployment and gateway topology. With the URL in the envelope:

- Actors are fully decoupled from gateway topology
- Different dispatchers can dispatch to the same actors
- Gateway URL changes don't require actor redeployment
- The URL is set at dispatch time by the dispatcher (knows its own Service)

### 3.4 Consistent Hash Routing via Ingress

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
      - path: /dispatch
        pathType: Exact
        backend:
          service: {name: asya-dispatcher, port: {number: 8080}}
---
# Everything else: consistent hash by envelope ID
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
      - path: /stream/
        pathType: Prefix
        backend:
          service: {name: asya-dispatcher, port: {number: 8080}}
      - path: /tasks/
        pathType: Prefix
        backend:
          service: {name: asya-dispatcher, port: {number: 8080}}
      - path: /a2a/
        pathType: Prefix
        backend:
          service: {name: asya-dispatcher, port: {number: 8080}}
```

**Internal Ingress** (sidecar-facing, always has the header):
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

**Why two Ingresses:**
- Different security blast radius (external vs cluster-internal)
- Different NetworkPolicies (agentgateway pods vs actor namespace pods)
- Can use different Ingress classes if needed
- Same hash algorithm -> same pod for same envelope ID

### 3.5 SSE Catch-Up on Reconnect

Between `POST /dispatch` and `GET /stream/{id}`, or after an SSE disconnect,
events may be missed. Standard fix -- catch up from DB on subscribe:

```go
func handleStream(w http.ResponseWriter, r *http.Request) {
    id := chi.URLParam(r, "id")

    // Catch up: check current state in DB
    task := db.Get(id)
    if task.IsTerminal() {
        writeSSEEvent(w, task.FinalStatus)
        return
    }

    // Subscribe for live events (in-memory Go channel)
    ch := subscribers.Add(id)
    defer subscribers.Remove(id, ch)

    // Stream events
    for event := range ch {
        writeSSEEvent(w, event)
        if event.IsTerminal() {
            return
        }
    }
}
```

### 3.6 Pod Failure Handling

```
Pod A holds SSE for "abc123"
Pod A is OOMKilled / node-drained

1. SSE connection drops (TCP reset)
2. Client reconnects: GET /stream/abc123 with X-Asya-Envelope-ID: abc123
3. Ketama hash ring rebalances: abc123 now maps to Pod B
4. Pod B: catches up from DB (current status), subscribes for live events
5. Sidecar's next POST: X-Asya-Envelope-ID: abc123 -> Ingress -> Pod B
   (same hash, same rebalanced ring)
6. Both sides converge on Pod B automatically
```

## 4. agentgateway Integration

### 4.1 Role: MCP Server + A2A Proxy

agentgateway handles ALL external protocol concerns:

| Protocol | agentgateway role | Dispatcher role |
|---|---|---|
| MCP | Full MCP server (tool federation, sessions) | Backend: /dispatch + /stream |
| A2A | Passthrough proxy (agent card rewriting) | Full A2A server |

### 4.2 MCP Flow via agentgateway

```
MCP Client          agentgateway              Dispatcher
  |                      |                        |
  | tools/call           |                        |
  | "my_flow"   -------->|                        |
  |                      | 1. POST /dispatch ---->| generates ID
  |                      |    <-- {id: "abc123"} -| dispatches to MQ
  |                      |                        |
  |                      | 2. GET /stream/abc123 >| SSE subscription
  |                      |    X-Asya-Envelope-ID  | (hash-routed)
  |                      |    <-- SSE events -----| Go channel -> SSE
  | <-- MCP response ----|                        |
  | (streaming)          |                        |
```

MCP client sees a single streaming tool response. The two-step is internal.

### 4.3 What agentgateway Provides (Free)

- MCP tool federation across multiple Asya meshes + external MCP servers
- Per-tool RBAC via CEL expressions
- Token-bucket + global rate limiting
- Content guardrails (regex, OpenAI moderation, Bedrock, Model Armor)
- OpenAPI-to-MCP auto-conversion
- Built-in admin UI + MCP playground
- Full OTLP observability with Jaeger/Langfuse integration
- MCP auth spec compliance (OIDC, Keycloak, Auth0)
- Session management (encrypted cookies, stateless mode)

### 4.4 agentgateway Config Example

```yaml
binds:
- port: 443
  tls: {cert: ..., key: ...}
  listeners:
  - routes:
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

    - policies:
        a2a: {}
        authentication:
          jwt: {jwksUrl: "https://..."}
      backends:
      - host: asya-dispatcher-ext
```

## 5. Sidecar Changes

### 5.1 Read Gateway URL from Envelope (eliminates ASYA_GATEWAY_URL)

```go
// Before: hardcoded at deploy time via env var
gatewayURL := os.Getenv("ASYA_GATEWAY_URL")

// After: read from envelope header
gatewayURL := envelope.Headers["x-asya-gateway-url"]
```

### 5.2 Set X-Asya-Envelope-ID Header on Every POST

```go
// Before: POST without routing header
req, _ := http.NewRequest("POST", gatewayURL+"/mesh/"+id+"/fly", body)

// After: add envelope ID header for Ingress consistent hash routing
req, _ := http.NewRequest("POST", gatewayURL+"/mesh/"+id+"/fly", body)
req.Header.Set("X-Asya-Envelope-ID", id)
```

Both changes are small and backward-compatible (sidecar can fall back to env
var if header is missing in older envelopes).

## 6. Database Role (Metadata Only)

The DB stores lightweight task metadata. It is NOT in the hot path for
real-time event delivery.

```sql
CREATE TABLE tasks (
    id          TEXT PRIMARY KEY,
    parent_id   TEXT,
    context_id  TEXT,
    status      TEXT NOT NULL,     -- pending/running/succeeded/failed/paused
    actor       TEXT,              -- current actor name
    progress    DECIMAL(5,2),      -- 0-100
    created_at  TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ
);
-- No payload JSONB. No result JSONB. No task_updates table.
-- Payload/result live in state-proxy (S3/GCS).
```

**Write pattern**: async fire-and-forget from mesh callback handlers.
**Read pattern**: catch-up on SSE reconnect, ListTasks for dashboard/A2A.
**Not used for**: real-time event delivery, pub/sub, FLY streaming.

Could be PostgreSQL, SQLite, or even NATS KV for simple deployments.

## 7. Component Responsibilities (Final)

| Component | Generates IDs? | Routes by hash? | Holds SSE? | Writes DB? |
|---|---|---|---|---|
| agentgateway | No | No | No | No |
| External Ingress | No | Yes (if header present) | No | No |
| Internal Ingress | No | Yes (always) | No | No |
| Dispatcher | Yes (POST /dispatch) | No | Yes | Yes (async) |
| Sidecar | No (reads from envelope) | No (sets header) | No | No |

| Concern | Owner |
|---|---|
| ID generation | Dispatcher (application) |
| Consistent hash routing | Ingress (networking) |
| Auth, rate limiting, MCP | agentgateway |
| Real-time event delivery | Dispatcher (in-process Go channels) |
| Task metadata persistence | Dispatcher -> DB (async) |
| Payload/result persistence | Actors -> state-proxy (S3/GCS) |

## 8. Code Impact

### 8.1 What Gets Deleted

| Component | LOC | Reason |
|---|---|---|
| internal/mcp/ (all) | ~1,868 | agentgateway replaces MCP server |
| internal/envelopestore/ (all) | ~1,593 | No PG pub/sub, simplified DB |
| internal/oauth/ (all) | ~521 | agentgateway handles auth |
| internal/toolstore/ (all) | ~515 | agentgateway discovers tools |
| internal/consumer/ | ~196 | No x-sink queue consumer |
| internal/a2a/auth.go | ~216 | agentgateway handles auth |
| internal/a2a/agent_card_producer.go | ~151 | agentgateway handles agent card |

### 8.2 What Gets Simplified

| Component | Before | After |
|---|---|---|
| A2A executor | ~266 LOC | ~150 LOC (no skill resolution) |
| A2A blocking wait | ~233 LOC | ~80 LOC (in-process subscribe, no DB poll) |
| A2A store adapter | ~312 LOC | ~100 LOC (read from state-proxy) |
| Queue integration | ~1,332 LOC | ~400 LOC (publish only, no pool mgmt) |
| Mesh handlers | ~759 LOC | ~300 LOC (deliver to subscriber + async DB) |
| Main wiring | ~439 LOC | ~150 LOC |

### 8.3 Net Result

- **Deleted**: ~5,060 LOC
- **Simplified**: ~3,341 -> ~1,180 LOC
- **New**: ~200 LOC (hash routing setup, two-step dispatch, Ingress config)
- **Total**: ~7,150 -> ~2,000 LOC (72% reduction)

## 9. A2A Protocol Mapping

| A2A method | Dispatcher endpoint | Routing |
|---|---|---|
| tasks/send | POST /dispatch | Round-robin (creates task) |
| tasks/get | GET /tasks/{id} | Hash-routed |
| tasks/subscribe | GET /stream/{id} | Hash-routed |
| tasks/sendSubscribe | POST /dispatch + GET /stream/{id} | Both |
| tasks/cancel | DELETE /tasks/{id} | Hash-routed |
| tasks/pushNotification | POST /a2a/notify | Hash-routed |

A2A `tasks/sendSubscribe` is implemented as the two-step internally.
agentgateway proxies A2A requests to the dispatcher's A2A handler.

## 10. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Timing gap between dispatch and subscribe | Low | DB catch-up on subscribe (standard pattern) |
| ListTasks without full SQL | Medium | Prefix scan via DB or state-proxy; most use cases are GetTask |
| nginx Ingress required for hash routing | Low | Standard component in most clusters |
| Sidecar breaking change (header + envelope URL) | Low | Backward-compatible: fall back to env var |
| agentgateway maturity | Medium | LF project with major backers; MCP-only, A2A stays in-house |
| Single pod handles all SSE for a hot task | Low | Rare in practice (1-2 subscribers per task) |
| Pod death during SSE | Low | Client reconnects, hash ring rebalances, DB catch-up |

## 11. What This Eliminates

| Current concern | Eliminated by |
|---|---|
| pg_notify (8KB limit, fragile) | In-process Go channels (SSE + mesh in same pod) |
| api/mesh gateway split | Single binary, two ports, two Ingresses |
| ASYA_GATEWAY_URL env var | x-asya-gateway-url in envelope header |
| PG as pub/sub bus | DB for metadata only (async writes) |
| MCP server code (~1,868 LOC) | agentgateway |
| Auth code (~755 LOC) | agentgateway |
| pg_listener.go (dedicated PG conn) | Not needed |
| task_updates table (SSE history) | DB catch-up on reconnect |
| x-sink queue consumer | Status via mesh HTTP callbacks |
| Create+subscribe conflation | Two-step API (POST /dispatch + GET /stream) |

## 12. Open Questions

1. Should the dispatcher expose a simple MCP server as fallback for
   non-agentgateway deployments?
2. Timeout enforcement: local timer per subscription? What happens when the
   owning pod restarts mid-timeout?
3. Migration path: can old gateway and new dispatcher run in parallel?
4. Should we support alternative Ingress controllers (Envoy Gateway
   BackendTrafficPolicy) or nginx-only?
5. Dashboard: separate client-level app reading from DB, or part of
   agentgateway's built-in admin UI?
