---
title: "RFC: agentgateway + asya-bridge Architecture"
---

# RFC: Replace asya-gateway with agentgateway + asya-bridge

## 1. Motivation

`asya-gateway` is a ~7,150 LOC Go monolith handling MCP, A2A, auth, task state
(PostgreSQL), SSE streaming, queue dispatch, mesh sidecar callbacks, and
observability. The api/mesh deployment split requires `pg_notify` for cross-process
sync, which has known problems:

- **8KB payload limit** on PG NOTIFY (FLY events regularly exceed this)
- **Dedicated PG connection** required (not from pool), with manual reconnect logic
- **Feedback loop risk**: `Save()` -> `Update()` -> `notifyListeners()` -> channel ->
  `Save()` again; required careful short-circuiting in `store_adapter.go`
- **2-second DB poll fallback** in `blocking.go` for oversized events
- **Lost status updates** when mesh gateway pod restarts during sidecar HTTP POST

## 2. agentgateway Research Findings

**Repository**: `github.com/agentgateway/agentgateway` (Apache 2.0, Linux Foundation)
**Language**: Rust (57.8%), Go controller (28%), TypeScript UI (11.6%)
**Backers**: AWS, Cisco, Microsoft, Red Hat, Huawei, Akamai
**Formerly**: Solo.io's AI gateway; donated to LF August 2025

### 2.1 MCP Support (Strong -- Full Server)

agentgateway implements a **real MCP server** with tool federation:

- Fans out `tools/list` to ALL upstream MCP servers
- Merges tool lists, prefixes names with `<target>_` to avoid collisions
- Routes `tools/call` to correct upstream by parsing tool name prefix
- Single-target mode: no prefix added
- Upstream transports: `stdio`, `sse`, `streamablehttp`, `openapi` (auto-converts
  OpenAPI specs into MCP tools)
- Session management: encrypted cookies (AES-256-GCM), stateful + stateless modes
- Failure modes: `failClosed` (default) or `failOpen` (skip unavailable targets)

### 2.2 A2A Support (Weak -- Passthrough Only)

agentgateway does NOT implement an A2A server:

- Classifies incoming JSON-RPC methods for logging (`tasks/send`, `message/stream`)
- Rewrites agent card URLs so clients don't bypass the gateway
- Does NOT inspect A2A responses
- No task state, no task ID generation, no pause/resume, no history
- Solo.io explicitly decided Envoy/existing proxies can't handle stateful A2A

### 2.3 Auth (Rich)

- JWT/JWKS validation (issuer, audience, required claims)
- API key (header or query param)
- OAuth 2.1 with PKCE (full authorization server)
- MCP Auth Spec compliance (RFC 9728, dynamic client registration)
- Provider adapters: Keycloak, Auth0
- **CEL-based per-tool RBAC**: `'jwt.role == "admin" || mcp.tool.name == "echo"'`
- External auth service integration (ExtAuth)
- Backend auth: GCP token, AWS SigV4, Azure managed identity

### 2.4 Observability

- Full OTLP export (metrics, traces, logs)
- Configurable sampling (random + CEL-based)
- Integrations: Jaeger, Phoenix, Langfuse, OpenLLMetry
- Structured JSON/text logging with CEL filters

### 2.5 Rate Limiting & Guardrails

- Token bucket (per-listener, configurable fill rate)
- Global rate limiting (external gRPC service)
- Guardrails: regex, OpenAI moderation, AWS Bedrock Guardrails, Google Model Armor,
  custom webhooks

### 2.6 Configuration

Three layers:
1. **Static**: env vars or YAML (global settings, set at startup)
2. **Local**: YAML with file-watch for dynamic reload
3. **XDS**: remote control plane using Envoy xDS transport but custom protobuf types
   (`agentgateway.dev.resource.Resource`)

Kubernetes CRDs:
- `AgentgatewayBackend` (agbe) -- backends: AI/LLM, MCP, static host, DFP
- `AgentgatewayPolicy` (agpol) -- traffic/frontend/backend policies via targetRefs
- Uses standard Gateway API resources (HTTPRoute, GRPCRoute)

### 2.7 Key Architectural Properties

- **Stateless**: no database, no persistent storage
- **No protocol translation**: A2A backends must speak A2A, MCP backends must speak MCP
  (exception: OpenAPI -> MCP auto-conversion)
- **Built-in web UI**: admin panel for exploring backends, routes, policies + MCP playground
- **Standalone binary**: single binary, no dependencies

## 3. asya-gateway Code Audit

### 3.1 Functionality Breakdown by Bucket

| Bucket | Key Files | LOC | Replaceable? |
|---|---|---|---|
| A2A Protocol | executor.go, translator.go, state.go, agent_card_producer.go, blocking.go, store_adapter.go | ~1,381 | No (agentgateway has no A2A server) |
| MCP Protocol | server.go, registry.go, handlers.go (MCP parts) | ~1,109 | Yes (agentgateway MCP is superior) |
| Task State Mgmt | pg_store.go, store.go, interface.go, pg_listener.go | ~1,593 | Eliminated (transport subjects replace PG) |
| SSE/Streaming | handlers.go (SSE parts), pg_listener.go | ~883 | Partially (passthrough yes, FLY generation no) |
| Queue Integration | queue.go, sqs.go, pubsub.go, rabbitmq.go, rabbitmq_pooled.go, channel_pool.go | ~1,332 | Moved to bridge (simplified) |
| Flow/Tool Registry | registry.go, types.go, watcher.go | ~515 | Deleted (agentgateway config) |
| Protocol Translation | translator.go, blocking.go, fly.go, registry.go, handlers.go | ~1,409 | No (Asya domain logic) |
| Mesh Callbacks | handlers.go (mesh parts) | ~759 | Eliminated (sidecar publishes to subjects) |
| Auth/Middleware | auth.go, oauth/server.go, pkce.go | ~755 | Yes (agentgateway auth is richer) |
| Observability | tracing.go, main.go (tracing parts) | ~518 | Yes (agentgateway OTLP is richer) |

### 3.2 PostgreSQL Schema

**`tasks` table** (20 columns):
- id, parent_id, context_id, status, payload (JSONB), result (JSONB), error,
  message, timeout_sec, deadline, remaining_timeout_sec, pause_metadata (JSONB),
  progress_percent, current_actor_name, actors_completed, total_actors,
  route_prev (TEXT[]), route_curr, route_next (TEXT[]), created_at, updated_at
- Indexes: status, created_at DESC, deadline, context_id

**`task_updates` table** (SSE history):
- id (BIGSERIAL), task_id (FK), status, message, result (JSONB), error,
  progress_percent, actor, task_state, partial_payload (JSONB, deprecated),
  timestamp
- Auto-cleanup: 24h for completed tasks

### 3.3 PostgreSQL's Three Roles

1. **Task state CRUD**: External clients query status/result/progress.
   Writes: Create (full envelope), Update (terminal status + result),
   UpdateProgress (route + progress + pause detection), Resume (deadline recalc).
   Reads: Get (point lookup by ID), GetUpdates (range by task_id + timestamp),
   IsActive (status + deadline check), List (filtered + paginated).

2. **Cross-process pub/sub** (`pg_notify`):
   Channel: `task_events`. Format: `task_id:event_type:payload_json`.
   Event types: `fly` (ephemeral FLY tokens), `progress` (persisted),
   `final` (persisted + result).
   FLY events are NEVER written to PG -- only broadcast via pg_notify.
   Size limit: 7900 bytes (100 bytes for framing overhead).
   Fallback: `NotifyFLY()` in-process for oversized payloads.
   Listener: `pg_listener.go` -- dedicated `*pgx.Conn` (not pool), auto-reconnect.

3. **SSE replay history**: `task_updates` table allows late-connecting SSE clients
   to catch up via `GetUpdates(taskID, since=timestamp)`.

### 3.4 Blocking Wait Pattern (A2A)

`blocking.go:waitAndRelayEvents()` uses dual detection:
- **Path 1**: In-process channel (`Subscribe(taskID)`) -- fires for same-pod updates
- **Path 2**: DB poll every 2 seconds (`Get(taskID)`) -- catches cross-pod updates
- pg_notify listener runs as separate goroutine, dispatches to subscribers
- Non-terminal updates are DROPPED to prevent feedback loop
- FLY events relayed as `TaskArtifactUpdateEvent{Append}` via eq.Write()
- `closeArtifactStream()` sends `LastChunk: true` before terminal events

## 4. State Proxy Assessment

### 4.1 Current Capabilities

asya-state-proxy is a Python sidecar providing virtual filesystem over storage:

- **Backends**: S3 (LWW/CAS/passthrough), GCS (LWW/CAS), Redis (CAS)
- **API**: HTTP/1.1 over Unix socket (`/var/run/asya/state/{name}.sock`)
- **Operations**: GET/PUT/HEAD/DELETE `/keys/{key}`, GET `/keys/?prefix=...`,
  GET/PUT `/meta/{key}` (xattr)
- **Consistency**: LWW (unconditional) or CAS (ETag/generation/WATCH-based)
- **No pub/sub**: purely request/response, no watches or subscriptions
- **No timestamps**: `stat()` returns size + is_file only
- **No NATS KV**: documented as planned but not implemented

### 4.2 Cannot Replace PG Directly

| Requirement | State Proxy | PostgreSQL | Gap |
|---|---|---|---|
| CRUD by ID | Yes | Yes | None |
| List with filters | Prefix only | SQL WHERE | No status/context filtering |
| Subscriptions | No | LISTEN/NOTIFY | No pub/sub at all |
| Update history | Manual | Automatic | No versioning |
| Transactions | CAS only | ACID | Optimistic only |
| Timestamps | No | Yes | No temporal queries |

### 4.3 Role in New Architecture

State-proxy remains for **actor persistent state** (its designed purpose).
For gateway task state, the transport's pub/sub subjects replace PG.
For durable history (A2A GetTask), x-sink already persists to state-proxy.

## 5. Proposed Architecture

### 5.1 Three-Layer Model

| Layer | Component | Responsibility | State |
|---|---|---|---|
| Protocol | agentgateway (Rust) | MCP server, A2A proxy, auth, rate limit, guardrails | Stateless |
| Translation | asya-bridge (Go, new) | HTTP <-> envelope <-> transport | Stateless |
| Mesh | sidecar + runtime + state-proxy | Execute actors, persist state, publish status | S3/GCS/Redis |

### 5.2 asya-bridge Endpoints

```
POST /dispatch          <- agentgateway MCP tool call
  - Create envelope (ID, route, payload, headers)
  - Publish to actor input queue
  - Subscribe to status.{envelope_id} subject
  - Stream FLY events or collect final result
  - Return result

POST /a2a/*             <- agentgateway A2A passthrough
  - A2A task lifecycle via transport subjects
  - Task state = latest retained message on status.{task_id}
  - History = read from state-proxy (x-sink persists there)

GET /stream/{id}        <- SSE for FLY events
  - Subscribe to fly.{id} subject
  - Stream as SSE

GET /tasks/{id}         <- Status query
  - Read latest from status.{id} retained subject (in-flight)
  - OR read from state-proxy (terminal tasks)
```

### 5.3 Sidecar Change

Sidecars stop POSTing to `/mesh/*` HTTP endpoints. Instead:

```go
// Before: HTTP POST to mesh gateway (can fail if pod restarting)
http.Post(meshGatewayURL+"/mesh/"+id+"/progress", body)
http.Post(meshGatewayURL+"/mesh/"+id+"/final", body)
http.Post(meshGatewayURL+"/mesh/"+id+"/fly", body)

// After: publish to transport subject (same queue client, durable)
queue.Publish("status."+id, progressMsg)
queue.Publish("status."+id, finalMsg)
queue.Publish("fly."+id, flyPayload)
```

Benefits:
- No lost updates on mesh gateway restart (transport is durable)
- No 8KB limit (transport message size >> 8KB)
- No dedicated PG connection for LISTEN
- Sidecar already has queue client -- zero new dependencies

### 5.4 Transport Subject Design

| Subject | Semantics | Retention | Purpose |
|---|---|---|---|
| `actor.{name}` | Queue (competing consumers) | Until ack | Work distribution (existing) |
| `status.{task_id}` | Pub/sub (fan-out) | Retained (last msg) or JetStream | Task state events |
| `fly.{task_id}` | Pub/sub (fan-out) | Ephemeral (no retention) | FLY token streams |
| `resume.{task_id}` | Pub/sub | Ephemeral | Pause/resume signal |
| `cancel.{task_id}` | Pub/sub | Ephemeral | Cancellation signal |

### 5.5 A2A Without PostgreSQL

| A2A Operation | Current (PG) | New (transport + state-proxy) |
|---|---|---|
| SendMessage | Create in PG, dispatch to queue | Publish envelope to queue + status.{id}: pending |
| GetTask | SELECT FROM tasks | Read status.{id} retained msg (in-flight) OR state-proxy (terminal) |
| GetTask+history | PG + state-proxy hydration | State-proxy only (x-sink already writes full history) |
| ListTasks | SELECT WHERE status=$1 | NATS KV prefix scan OR state-proxy prefix list (degraded) |
| Subscribe (SSE) | PG listener + channels | Subscribe to status.{id} + fly.{id} subjects |
| Pause | PG update + pause_metadata | x-pause writes to state-proxy, publishes status.{id}: paused |
| Resume | PG update + deadline recalc | Bridge publishes to resume.{id}, x-resume reads state-proxy |
| Cancel | PG update | Publish status.{id}: canceled + cancel.{id} |
| Timeout | PG deadline column + timer | Bridge local timer; on expiry publishes status.{id}: failed |

## 6. Transport Comparison

| Transport | Pub/Sub | Retained/Replay | KV Store | Fit |
|---|---|---|---|---|
| NATS+JetStream | Native subjects | JetStream consumers with replay | NATS KV built-in | Best -- all-in-one |
| RabbitMQ | Topic exchanges + temp queues | Not built-in (plugin/manual) | No | Good -- pub/sub works |
| Google Pub/Sub | Native | Seek to timestamp | No | Good -- pub/sub + replay |
| SQS | No (needs SNS) | No | No | Weak -- needs SNS fan-out |

NATS is the strongest fit: pub/sub subjects, JetStream for durable replay, NATS KV
for task state lookups -- all in one system. RabbitMQ and Pub/Sub work but need
additional components for retained messages and KV.

## 7. agentgateway Configuration Example

```yaml
binds:
- port: 443
  tls: {cert: ..., key: ...}
  listeners:
  - routes:
    # MCP: agentgateway is the MCP server, bridge is a backend
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
      - host: asya-bridge:8080
        mcp:
          transport: streamablehttp

    # A2A: passthrough to bridge's A2A server
    - policies:
        a2a: {}
        authentication:
          jwt: {jwksUrl: "https://..."}
      backends:
      - host: asya-bridge:8080
```

## 8. Code Impact

| asya-gateway component | LOC | Verdict |
|---|---|---|
| internal/mcp/server.go | 59 | Delete (agentgateway) |
| internal/mcp/registry.go | 291 | Delete (agentgateway) |
| internal/mcp/handlers.go | 759 | Simplify to /dispatch endpoint |
| internal/a2a/auth.go | 216 | Delete (agentgateway) |
| internal/a2a/executor.go | 266 | Simplify (no skill resolution -- agentgateway routes) |
| internal/a2a/translator.go | 103 | Keep (A2A message -> envelope payload) |
| internal/a2a/blocking.go | 233 | Rewrite (subscribe to transport subject, no DB poll) |
| internal/a2a/store_adapter.go | 312 | Rewrite (read from state-proxy, no PG) |
| internal/a2a/agent_card_producer.go | 151 | Delete (agentgateway handles agent card) |
| internal/a2a/state.go | 54 | Keep (state enum mapping) |
| internal/envelopestore/ (all) | 1,593 | Delete entirely |
| internal/oauth/ (all) | 521 | Delete (agentgateway) |
| internal/queue/ (all) | 1,332 | Simplify (publish + subscribe only) |
| internal/consumer/ | 196 | Delete (status comes via subject) |
| internal/toolstore/ (all) | 515 | Delete (agentgateway discovers tools) |
| internal/tracing/ | 79 | Simplify (span propagation only) |
| internal/stateproxy/ | 78 | Keep (read from state-proxy for A2A) |
| cmd/gateway/main.go | 439 | Rewrite (much simpler wiring) |

Estimated result: ~7,150 LOC -> ~1,500-2,000 LOC (70-75% reduction).

## 9. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| ListTasks degraded without SQL | Medium | Prefix scan in NATS KV / state-proxy; most AI agent use cases are GetTask-by-ID |
| SSE replay for late joiners | Medium | JetStream replay from sequence; or accept FLY is ephemeral |
| SQS deployments lack pub/sub | High | SNS fan-out adapter; or accept SQS keeps current arch |
| Sidecar breaking change | Low | Well-scoped: publish to subject instead of HTTP POST |
| Two deployments (agentgateway + bridge) | Low | agentgateway is single binary; bridge is tiny |
| agentgateway maturity | Medium | LF project, major backers, but ~1 year old |
| NATS becomes load-bearing | Medium | Already supported transport; proven at scale |
| x-sink consumer removal | Low | Status comes via subject; x-sink still persists to state-proxy |

## 10. New Capabilities (Free from agentgateway)

- MCP tool federation across multiple Asya meshes + external MCP servers
- Per-tool RBAC via CEL expressions
- Token-bucket + global rate limiting
- Content guardrails (regex, OpenAI moderation, Bedrock, Model Armor, webhooks)
- OpenAPI-to-MCP auto-conversion (any REST API as MCP tool)
- Built-in admin UI + MCP playground
- Full OTLP observability with Jaeger/Langfuse integration
- MCP auth spec compliance (OIDC, Keycloak, Auth0)
- Health-based backend eviction with CEL expressions
- Session management (encrypted cookies, stateless mode)

## 11. Key Insight: Why This Works

The fundamental insight is that the message transport already provides the
distributed coordination primitive that PG was being forced into. Sidecars
already have queue clients. Publishing status to a subject is the same operation
as sending an envelope to the next actor. The transport gives us:

- **Pub/sub** (replaces pg_notify)
- **Retention** (replaces tasks table for in-flight state)
- **Durability** (replaces lost HTTP POSTs to restarting mesh gateway)
- **No size limit** (replaces 8KB pg_notify constraint)

PostgreSQL was an impedance mismatch -- a relational database used as a pub/sub
bus. The transport is purpose-built for this.

## 12. Open Questions

1. Should bridge expose MCP directly (for non-agentgateway deployments) or is
   agentgateway always required?
2. How to handle timeout enforcement in a stateless bridge? (Local timer per
   subscription? What if bridge pod restarts?)
3. Should NATS KV store a task index for ListTasks? Or is state-proxy prefix
   listing sufficient?
4. Migration path: can we run old gateway + new bridge in parallel during
   transition?
5. Does agentgateway's A2A passthrough rewrite enough (agent card URLs) or do
   we need custom A2A handling in agentgateway too?
