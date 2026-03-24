# Gateway

## Responsibilities

- Expose MCP-compliant HTTP API
- Create tasks from HTTP requests
- Track task status in PostgreSQL
- Stream progress updates and ephemeral FLY events via Server-Sent Events (SSE)
- Receive status reports from crew actors
- Broadcast FLY events via PG LISTEN/NOTIFY for cross-process delivery

## How It Works

1. Client calls MCP tool via HTTP POST
2. Gateway creates task with unique ID
3. Gateway stores task in PostgreSQL (status: `pending`)
4. Gateway sends envelope to first actor's queue
5. Crew actors (`x-sink`, `x-sump`) report final task status
6. Client polls or streams task status updates via SSE

## Deployment

The gateway binary supports three modes via `ASYA_GATEWAY_MODE`:

| Mode | Routes | Use |
|------|--------|-----|
| `api` | A2A, MCP, OAuth, health | External-facing; behind Ingress |
| `mesh` | Mesh routes, health | Internal-only; ClusterIP, no Ingress |
| `testing` | All routes | Local development and integration tests |

### State ownership

The gateway uses two independent state stores with clearly separated ownership:

```
                        ┌─────────────────────────────┐
                        │   gateway-flows ConfigMap   │
                        │   (flows.yaml — K8s object) │
                        └──────────────┬──────────────┘
                                       │ polls every 10 s
                                       │ (toolstore.Watch)
                        ┌──────────────▼──────────────┐
   external client ───► │        api pod              │
   MCP / A2A / OAuth    │  - MCP dispatch             │
                        │  - A2A routing              │
                        │  - agent card               │
                        └──────────────┬──────────────┘
                                       │ sends envelope
                                       ▼
                                  actor queue
                                       │
                                       ▼
                                  actor pod
                                       │ POST /mesh/{id}/…
                        ┌──────────────▼──────────────┐
                        │        mesh pod             │
                        │  - progress callbacks       │
                        │  - final status             │
                        │  - SSE fan-out              │
                        └──────────────┬──────────────┘
                                       │ reads / writes
                        ┌──────────────▼──────────────┐
                        │        PostgreSQL           │
                        │  tasks, task_updates        │
                        │  oauth_clients, tokens      │
                        └─────────────────────────────┘
                                       ▲
                        ───────────────┘
                        api pod also reads/writes
                        (task creation, OAuth, GetTask)
```

**ConfigMap** (`gateway-flows`) — routing configuration:

| | api pod | mesh pod |
|---|---|---|
| Mounts ConfigMap | ✅ (`ASYA_CONFIG_PATH`) | ❌ |
| Hot-reloads on change | ✅ every 10 s (default) | ❌ |
| Uses for dispatch | ✅ MCP + A2A + agent card | ❌ |

The ConfigMap is the source of truth for *what flows exist*. It is seeded by
Helm at deploy time and can be patched at runtime (e.g., via `kubectl patch` or
`asya mcp expose`) without a pod restart.

**Database** — task and auth state (PostgreSQL):

| | api pod | mesh pod |
|---|---|---|
| Creates tasks | ✅ (on MCP/A2A call) | ❌ |
| Writes progress | ❌ | ✅ (via `/mesh/{id}/progress`) |
| Writes final status | ❌ | ✅ (via `/mesh/{id}/final`) |
| Reads task state | ✅ (GetTask, SSE, OAuth) | ✅ (SSE stream) |
| Stores OAuth clients/tokens | ✅ (when OAuth enabled) | ❌ |

Both pods connect to the **same** database instance. The database is the shared
coordination point: the api pod creates a task record, then mesh pod workers
update it as actors report progress.

The storage layer is abstracted internally. PostgreSQL is the provided
implementation — it handles metadata and task state well for all current use
cases. Additional backends may be added if specific requirements emerge. Note
that this is distinct from the pluggable **transports** (SQS, RabbitMQ, Pub/Sub)
and pluggable **state proxy connectors** (S3, GCS, Redis, NATS KV), which are
designed for high-throughput data paths.

Production deployments use **two Helm releases** from the same chart:

```bash
# External-facing API gateway (with Ingress)
helm install asya-gateway deploy/helm-charts/asya-gateway/ \
  --set mode=api \
  -f gateway-values.yaml

# Internal mesh gateway (ClusterIP only, no Ingress)
helm install asya-gateway-mesh deploy/helm-charts/asya-gateway/ \
  --set mode=mesh \
  -f gateway-mesh-values.yaml
```

Both releases share the same container image and database. Sidecars
and crew actors reach the mesh deployment via in-cluster DNS:
`asya-gateway-mesh.<namespace>.svc.cluster.local`.

**Gateway is stateful**: Requires a database (PostgreSQL) for task tracking and
(when OAuth is enabled) for OAuth client/token storage.

## Configuration

Configured via Helm values. Key sections:

```yaml
# gateway-values.yaml
mode: api  # api | mesh | testing
config:
  sqsRegion: "us-east-1"
  postgresHost: "postgres.default.svc.cluster.local"
  postgresDatabase: "asya_gateway"
  postgresPasswordSecretRef:
    name: postgres-secret
    key: password
```

Tool/skill registration is **ConfigMap-backed**: flows are declared in
`flows.yaml`, mounted into the api pod, and hot-reloaded every 10 seconds (configurable via `ASYA_CONFIG_POLL_INTERVAL`) by a
polling watcher (`toolstore.Watch`). Updating the ConfigMap is the only way to
add, change, or remove an exposed tool or A2A skill — no restart is needed.

The Helm chart creates an empty `gateway-flows` ConfigMap. After deployment,
flows are registered by patching the ConfigMap (e.g., via `asya flow expose`
or `kubectl patch`). No Helm upgrade is needed.

## API Endpoints

**See**: [Gateway API spec](../specs/gateway-api.md) for the full API reference with complete request/response schemas for all routes.



Routes are split across the two deployments.

### External API routes (`mode: api`)

#### MCP endpoints

```bash
POST /mcp        # MCP Streamable HTTP transport (recommended)
GET  /mcp/sse    # MCP SSE transport (for clients that require SSE)
POST /tools/call # MCP tool invocation (REST convenience path)
```

Both `/mcp` and `/mcp/sse` are active transports — neither is deprecated. Use
whichever your MCP client supports.

```bash
GET  /.well-known/agent.json   # A2A Agent Card (public, no auth)
POST /a2a/                     # A2A JSON-RPC endpoint
```

OAuth 2.1 endpoints (when `ASYA_MCP_OAUTH_ENABLED=true`):

```bash
GET  /.well-known/oauth-protected-resource    # RFC 9728 resource metadata
GET  /.well-known/oauth-authorization-server  # RFC 8414 server metadata
POST /oauth/register                          # Dynamic Client Registration
GET  /oauth/authorize                         # Authorization Code endpoint
POST /oauth/token                             # Token exchange and refresh
```

### Mesh routes (`mode: mesh`)

Called exclusively by sidecars and crew actors within the cluster.

#### Call Tool (REST, external api mode)

```bash
POST /tools/call
Content-Type: application/json

{
  "name": "text-processor",
  "arguments": {
    "text": "Hello world",
    "model": "gpt-4"
  }
}
```

Response (MCP CallToolResult):
```json
{
  "content": [
    {
      "type": "text",
      "text": "{\"task_id\":\"5e6fdb2d...\",\"message\":\"Task created successfully\",\"status_url\":\"/mesh/5e6fdb2d...\",\"stream_url\":\"/mesh/5e6fdb2d.../stream\"}"
    }
  ],
  "isError": false
}
```

See [Envelope Protocol](../specs/envelope.md) for more details on task statuses.

#### Get Task Status

```bash
GET /tasks/{id}
```

Response:
```json
{
  "id": "5e6fdb2d-1d6b-4e91-baef-73e825434e7b",
  "status": "succeeded",
  "message": "Task completed successfully",
  "result": {"response": "Processed: Hello world"},
  "progress_percent": 100,
  "current_actor_idx": 2,
  "current_actor_name": "postprocess",
  "actors_completed": 3,
  "total_actors": 3,
  "created_at": "2025-11-18T12:00:00Z",
  "updated_at": "2025-11-18T12:01:30Z"
}
```

#### Stream Task Updates (SSE)

```bash
GET /mesh/{id}/stream
Accept: text/event-stream
```

Internal mesh endpoint for streaming progress and FLY events. For external API access, use `GET /stream/{id}` on the API gateway.

**Features**:

- Sends historical progress and status updates first (no missed progress)
- Streams real-time updates as they occur
- Broadcasts ephemeral FLY events via PG LISTEN/NOTIFY for cross-process delivery
- Keepalive comments every 15 seconds
- Auto-closes on final status (`succeeded` or `failed`)

⚠️ **FLY events are ephemeral** — not persisted to the database. Clients connecting after task completion will NOT see historical FLY events.

Stream events (TaskUpdate):
```
event: update
data: {"id":"task-123","status":"running","progress_percent":10,"current_actor_idx":0,"actor_state":"received","actor":"preprocess","actors":["preprocess","infer","post"],"message":"Actor preprocess: received","timestamp":"2025-11-18T12:00:15Z"}

event: update
data: {"id":"task-123","status":"running","progress_percent":33,"current_actor_idx":0,"actor_state":"completed","actor":"preprocess","actors":["preprocess","infer","post"],"message":"Actor preprocess: completed","timestamp":"2025-11-18T12:00:20Z"}

event: update
data: {"id":"task-123","status":"running","progress_percent":66,"current_actor_idx":1,"actor_state":"completed","actor":"infer","actors":["preprocess","infer","post"],"message":"Actor infer: completed","timestamp":"2025-11-18T12:01:00Z"}

event: update
data: {"id":"task-123","status":"succeeded","progress_percent":100,"result":{...},"message":"Task completed successfully","timestamp":"2025-11-18T12:01:30Z"}
```

**TaskUpdate fields**:

- `id`: Task ID
- `status`: Task status (`pending`, `running`, `succeeded`, `failed`)
- `progress_percent`: Progress 0-100 (omitted if not a progress update)
- `current_actor_idx`: Current actor index (0-based, omitted for final states)
- `actor_state`: Actor processing state (`received`, `processing`, `completed`)
- `actor`: Current actor name (omitted for final states)
- `actors`: Full route (may be modified via VFS)
- `message`: Human-readable status message
- `result`: Final result (only for `succeeded` status)
- `error`: Error message (only for `failed` status)
- `timestamp`: When this update occurred

#### Check Task Active

```bash
GET /mesh/{id}/active
```

**Used by**: Actors to verify task hasn't timed out

Response (active):
```json
{"active": true}
```

Response (inactive - HTTP 410 Gone):
```json
{"active": false}
```

### Mesh endpoints (Sidecar/Crew, `mode: mesh`)

#### Report Progress

```bash
POST /mesh/{id}/progress
Content-Type: application/json

{
  "actors": ["prep", "infer", "post"],
  "current_actor_idx": 0,
  "status": "completed"
}
```

**Called by**: Sidecars at three points per actor (`received`, `processing`, `completed`)

**Progress formula**: `(actor_idx * 100 + status_weight) / total_actors`
- `received` = 10, `processing` = 50, `completed` = 100

**Unknown task IDs**: Progress updates for tasks not found in the store are
silently accepted (200 OK). This is expected for direct-SQS envelopes that bypass
gateway task creation. Infrastructure errors (e.g., database failures) still
return 500.

Response:
```json
{"status": "ok", "progress_percent": 33.3}
```

#### Report Final Status

```bash
POST /mesh/{id}/final
Content-Type: application/json

{
  "id": "task-123",
  "status": "succeeded",
  "result": {...}
}
```

**Called by**: `x-sink` (success) or `x-sump` (failure) crew actors

#### Create Fanout Task

```bash
POST /tasks
Content-Type: application/json

{
  "id": "task-123-1",
  "parent_id": "task-123",
  "actors": ["prep", "infer"],
  "current": 1
}
```

**Called by**: Sidecars when runtime returns array (fan-out)

**Fanout ID semantics**:

- Index 0: Original ID (`task-123`)
- Index 1+: Suffixed (`task-123-1`, `task-123-2`)
- All children have `parent_id` for traceability

### Health Check

```bash
GET /health
```

Response: `OK`

## Flow Examples

Flows are declared in `flows.yaml` (mounted as a ConfigMap). Each entry is a
`FlowConfig` that maps a name to an actor pipeline and declares whether it is
exposed as an MCP tool, an A2A skill, or both.

**Single-actor MCP tool**:
```yaml
flows:
- name: hello
  entrypoint: hello-actor
  description: Say hello
  mcp:
    inputSchema:
      type: object
      properties:
        who:
          type: string
          description: Name to greet
      required: [who]
```

**Multi-actor pipeline exposed as both MCP and A2A**:
```yaml
flows:
- name: image-enhance
  entrypoint: download-image
  route_next: [enhance, upload]
  description: Enhance image quality
  timeout: 120
  mcp:
    inputSchema:
      type: object
      properties:
        image_url:
          type: string
          description: URL of image to enhance
        quality:
          type: string
          description: "Target quality: low | medium | high"
      required: [image_url]
  a2a: {}
```

**Fields**:

| Field | Required | Description |
|---|---|---|
| `name` | ✅ | Unique flow name; becomes the MCP tool name and A2A skill name |
| `entrypoint` | ✅ | First actor in the pipeline (queue name without `asya-<ns>-` prefix) |
| `route_next` | ❌ | Ordered list of subsequent actors |
| `description` | ❌ | Human-readable description surfaced in tool/skill listings |
| `timeout` | ❌ | Max seconds to wait for completion (default: no limit) |
| `mcp` | ❌ | Present → exposed as MCP tool; `inputSchema` is the JSON Schema for arguments |
| `a2a` | ❌ | Present → exposed as A2A skill |

## Authentication & Security

The gateway implements protocol-native authentication on external routes and
network-level isolation for mesh routes. No auth code runs on mesh routes —
they are unreachable from outside the cluster by design.

| Route group | Auth mechanism |
|-------------|---------------|
| A2A (`/a2a/`) | API key (`X-API-Key`) or JWT Bearer — configured via `ASYA_A2A_*` env vars |
| MCP (`/mcp`, `/mcp/sse`, `/tools/call`) | API key Bearer or OAuth 2.1 token — configured via `ASYA_MCP_*` env vars |
| Mesh (`/mesh/…`) | None — ClusterIP only, unreachable externally |
| Well-known + health | Always public |

### A2A Authentication

Two schemes are supported with OR semantics — a request is authenticated if
either check passes:

**API Key**

```
X-API-Key: <value>
```

Configured via `ASYA_A2A_API_KEY`. When set, the header value must match
exactly (constant-time comparison).

**JWT Bearer**

```
Authorization: Bearer <JWT>
```

Configured via `ASYA_A2A_JWT_JWKS_URL` + `ASYA_A2A_JWT_ISSUER` +
`ASYA_A2A_JWT_AUDIENCE`. The gateway fetches the JWKS from the configured URL
and validates the token signature, issuer, and audience claims.

When neither `ASYA_A2A_API_KEY` nor `ASYA_A2A_JWT_JWKS_URL` is set, A2A auth
is disabled (all requests pass). This is the default for local development.

The public Agent Card at `/.well-known/agent.json` advertises the configured
schemes. Authenticated clients access only their own tasks — the gateway must
not reveal the existence of tasks belonging to other clients.

### MCP Authentication

MCP auth is applied to `/mcp`, `/mcp/sse`, and `/tools/call`. Two modes are
mutually exclusive:

**API Key (simple, non-spec-compliant)**

```
Authorization: Bearer <static-key>
```

Set `ASYA_MCP_API_KEY` to a shared secret. Suitable for internal tooling
(`asya-lab` CLI, known MCP hosts) where full OAuth is not needed.

When `ASYA_MCP_API_KEY` is empty, MCP auth is disabled.

**OAuth 2.1 (full MCP spec compliance)**

Set `ASYA_MCP_OAUTH_ENABLED=true` plus `ASYA_MCP_OAUTH_ISSUER` and
`ASYA_MCP_OAUTH_SECRET`. The gateway acts as its own authorization server,
issuing HMAC-SHA256 JWTs. PostgreSQL is required (`ASYA_DATABASE_URL`).

Scopes (issued but not yet enforced per-endpoint):

| Scope | Intended permission |
|-------|-------------------|
| `mcp:invoke` | Call tools, send messages |
| `mcp:read` | List tools, read task state |

Scopes are issued into access tokens and stored in the database. However,
`MCPAuthMiddleware` currently only validates that a token is authentic (signature,
`iss`, `aud`, `exp`) — it does **not** check that the token's scope is sufficient
for the specific operation being requested.

OAuth 2.1 endpoints (when `ASYA_MCP_OAUTH_ENABLED=true`):

```bash
GET  /.well-known/oauth-protected-resource    # RFC 9728 resource metadata
GET  /.well-known/oauth-authorization-server  # RFC 8414 server metadata
POST /oauth/register                          # Dynamic Client Registration
GET  /oauth/authorize                         # Authorization Code endpoint
POST /oauth/token                             # Token exchange and refresh
```

PKCE (`code_challenge_method=S256`) is required for all clients.

Dynamic Client Registration (`/oauth/register`) is public by default. To restrict
it, set `ASYA_MCP_OAUTH_REGISTRATION_TOKEN` — callers must then supply
`Authorization: Bearer <registration-token>` to register.

### Mesh Security

Mesh routes carry no authentication code. Security is enforced at the network
layer:

- `asya-gateway-mesh` K8s Service is `ClusterIP` — no Ingress, no NodePort.
  It is physically unreachable from outside the cluster.
- Sidecars and crew actors reach it via in-cluster DNS:
  `asya-gateway-mesh.<namespace>.svc.cluster.local`.

For defence in depth, add a K8s NetworkPolicy restricting ingress to actor pods:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: gateway-mesh-ingress
spec:
  podSelector:
    matchLabels:
      app: asya-gateway-mesh
  ingress:
    - from:
        - podSelector:
            matchLabels:
              asya.sh/component: actor
      ports:
        - port: 8080
```

Alternatively, enable a service mesh (Istio/Linkerd) for automatic mTLS between
all pods with zero Asya code changes.

### Environment Variables

All auth-related environment variables:

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ASYA_GATEWAY_MODE` | — | Yes | `api`, `mesh`, or `testing` |
| `ASYA_DATABASE_URL` | `""` | For OAuth 2.1 | PostgreSQL DSN; required when `ASYA_MCP_OAUTH_ENABLED=true` |
| **A2A** | | | |
| `ASYA_A2A_API_KEY` | `""` | No | Static API key; auth disabled when empty |
| `ASYA_A2A_JWT_JWKS_URL` | `""` | No | JWKS endpoint URL for JWT validation |
| `ASYA_A2A_JWT_ISSUER` | `""` | With JWKS | Expected `iss` claim |
| `ASYA_A2A_JWT_AUDIENCE` | `""` | With JWKS | Expected `aud` claim |
| **MCP Phase 2** | | | |
| `ASYA_MCP_API_KEY` | `""` | No | Static Bearer token; auth disabled when empty |
| **MCP Phase 3 (OAuth 2.1)** | | | |
| `ASYA_MCP_OAUTH_ENABLED` | `false` | No | Set to `true` to enable OAuth 2.1 |
| `ASYA_MCP_OAUTH_ISSUER` | `""` | Yes (OAuth) | Issuer URL embedded in tokens and metadata |
| `ASYA_MCP_OAUTH_SECRET` | `""` | Yes (OAuth) | HMAC-SHA256 signing key for access tokens |
| `ASYA_MCP_OAUTH_TOKEN_TTL` | `3600` | No | Access token lifetime in seconds |
| `ASYA_MCP_OAUTH_REGISTRATION_TOKEN` | `""` | No | Bearer token protecting `/oauth/register`; empty = open |

## Using MCP tools
**See**: [Quickstart](../../setup/start-quickstart.md) for instructions how to test MCP locally.

## Deployment Helm Charts

**See**: [Gateway Setup Guide](../../setup/guide-gateway.md) for gateway chart details.
