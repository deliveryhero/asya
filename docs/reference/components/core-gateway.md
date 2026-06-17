---
description: "Gateway (Go): split mesh-api + mcp-adapter + a2a-adapter containers, pluggable pg-kv/pvc-kv state, SSE streaming"
---

# Gateway

## Responsibilities

- Expose MCP- and A2A-compliant HTTP APIs
- Create tasks from HTTP requests
- Track task status in a pluggable state backend (PostgreSQL or local files)
- Stream progress updates and ephemeral FLY events via Server-Sent Events (SSE)
- Receive status reports from sidecars and crew actors
- Fan out SSE events to subscribed clients

## How It Works

1. Client calls an MCP tool or A2A skill via HTTP
2. The adapter (mcp-adapter / a2a-adapter) forwards to the local mesh-api
3. mesh-api creates a task with a unique ID (status: `pending`)
4. mesh-api stores the task via the state-proxy sidecar
5. mesh-api sends the envelope to the first actor's queue
6. Crew actors (`x-sink`, `x-sump`) report final task status to mesh-api
7. Client polls or streams task status updates via SSE

## Deployment

The gateway is **one image** (`asya-gateway`) that ships three binaries. Each runs
as a separate container in a single pod, selected via the container `command:`:

| Container | Command | Ports | Role |
|-----------|---------|-------|------|
| `mesh-api` | _(default entrypoint)_ | 8080 (external), 8081 (internal) | Core HTTP server: task CRUD, SSE, queue publish, sidecar callbacks |
| `mcp-adapter` | `./mcp-adapter` | 8082 | MCP Streamable HTTP — translates `tools/list` / `tools/call` into mesh-api calls |
| `a2a-adapter` | `./a2a-adapter` | 8083 | A2A JSON-RPC — implements the A2A protocol over mesh-api calls |

A fourth container, the **state-proxy-mesh** sidecar, persists task/mesh state.
The mesh-api never talks to a database directly — it issues KV operations to the
state-proxy over a Unix socket, and the state-proxy translates them to its backend.

The adapters are optional (`mcp.enabled` / `a2a.enabled` in Helm values). mesh-api
and its state-proxy are always present.

### State backend (pluggable)

The state-proxy backend is selected by `stateProxy.mesh.backend`:

| Backend | Storage | Replicas | When to use |
|---------|---------|----------|-------------|
| `pg-kv` _(default)_ | PostgreSQL | Multiple | Production; horizontal scaling, durable shared state |
| `pvc-kv` | DuckDB over JSON files on a PVC, or in-memory | `replicaCount: 1` only | Lightweight deployments, demos, environments without PostgreSQL |

**PostgreSQL is no longer mandatory.** With `pvc-kv` the gateway keeps task state
in local files (or memory) and requires no external database. Because local storage
is not shared across pods, `pvc-kv` enforces `replicaCount: 1` (the chart fails the
render otherwise).

The state layer is distinct from the pluggable **transports** (SQS, RabbitMQ,
Pub/Sub) used to publish envelopes to actor queues, and from the actor-side
**state proxy connectors** (S3, GCS, Redis, NATS KV) used for high-throughput data.

### State ownership

```
                        ┌─────────────────────────────┐
   external client ───► │   mcp-adapter (:8082)       │
   MCP                  │   a2a-adapter (:8083)       │
   A2A                  └──────────────┬──────────────┘
                                       │ POST /api/v1/mesh/ (create)
                                       │ GET  /api/v1/mesh/{id} (status)
                        ┌──────────────▼──────────────┐
                        │   mesh-api external (:8080) │
                        │   - task create / list      │
                        │   - GET {id} / SSE events   │
                        │   - DELETE {id} (cancel)    │
                        └──────────────┬──────────────┘
                                       │ sends envelope
                                       ▼
                                  actor queue
                                       │
                                       ▼
                                  actor pod
                                       │ POST /api/v1/mesh/{id}/events
                        ┌──────────────▼──────────────┐
                        │   mesh-api internal (:8081) │
                        │   - status + FLY callbacks  │
                        │   - sidecar heartbeat (GET) │
                        └──────────────┬──────────────┘
                                       │ KV ops over Unix socket
                        ┌──────────────▼──────────────┐
                        │   state-proxy-mesh sidecar  │
                        │   pg-kv → PostgreSQL        │
                        │   pvc-kv → local files/mem  │
                        └─────────────────────────────┘
```

The mesh-api exposes **two ports**:

- **External (8080)** — client-facing: task create/list, get, cancel, SSE subscribe.
  Reachable via the `asya-gateway-mesh-api` Service and (optionally) Ingress.
- **Internal (8081)** — sidecar callbacks: publish status/FLY events, heartbeat
  check. Reachable only in-cluster via the `asya-gateway-mesh-api-int` Service.
  Sidecars learn this URL from the `x-asya-gateway-url` envelope header, stamped
  by mesh-api from `ASYA_INTERNAL_URL`.

### Services

The chart renders four Services (release name `asya-gateway`):

| Service | Port | Type | Audience |
|---------|------|------|----------|
| `asya-gateway-mesh-api` | 8080 | ClusterIP | External clients (via Ingress) |
| `asya-gateway-mesh-api-int` | 8081 | ClusterIP | Sidecars / crew (in-cluster only) |
| `asya-gateway-mcp` | 8082 | ClusterIP | MCP clients (rendered when `mcp.enabled`) |
| `asya-gateway-a2a` | 8083 | ClusterIP | A2A clients (rendered when `a2a.enabled`) |

External exposure is via the Ingress (`ingress.enabled`), not a per-deployment
LoadBalancer. The mesh-api-int Service has no Ingress and is unreachable from
outside the cluster by design.

## Configuration

Configured via Helm values. Key sections:

```yaml
# gateway-values.yaml

stateProxy:
  mesh:
    backend: pg-kv   # pg-kv (PostgreSQL) | pvc-kv (local files / in-memory)

# Only consulted by the pg-kv backend:
database:
  host: postgres.default.svc.cluster.local
  port: 5432
  name: asya_gateway
  username: asya
  existingSecret: postgres-secret   # key "password" by default
  sslMode: require

transports:
  pubsub:
    enabled: true     # exactly one of rabbitmq | sqs | pubsub
    config:
      projectId: my-project

mcp:
  enabled: true
a2a:
  enabled: true
  auth:
    apiKey: ""        # ASYA_A2A_API_KEY
    jwt:
      jwksURL: ""
      issuer: ""
      audience: ""
```

Tool and skill registration is **ConfigMap-backed**. MCP tools are mounted into
the mcp-adapter (`mcpTools` values) and A2A agents into the a2a-adapter
(`a2aAgents` values). Each adapter hot-reloads its ConfigMap by polling every
`ASYA_MCP_POLL_INTERVAL` / `ASYA_A2A_POLL_INTERVAL` (default `10s`). No restart is
needed to add, change, or remove a tool or skill.

**See**: [Gateway Setup Guide](../../setup/guide-gateway.md) for how flows are
compiled into these ConfigMaps and registered.

## API Endpoints

**See**: [Gateway API spec](../specs/gateway-api.md) for full request/response schemas.

### mesh-api external routes (port 8080)

```bash
POST   /api/v1/mesh/            # Create task (returns task ID)
GET    /api/v1/mesh/            # List tasks
GET    /api/v1/mesh/{id}        # Get task status
GET    /api/v1/mesh/{id}/events # Subscribe to SSE updates
DELETE /api/v1/mesh/{id}        # Cancel task
GET    /health                  # Liveness
GET    /ready                   # Readiness (checks state-proxy reachability)
```

The route prefix is configurable via `ASYA_MESH_API_PREFIX` (default `/api/v1`;
set to `""` for unprefixed `/mesh/` routes).

### mesh-api internal routes (port 8081)

Called exclusively by sidecars and crew actors within the cluster.

```bash
POST /api/v1/mesh/{id}/events  # Publish status + FLY events (sidecar)
GET  /api/v1/mesh/{id}         # Heartbeat / pre-flight check (sidecar)
```

#### Publish events

```bash
POST /api/v1/mesh/{id}/events
Content-Type: application/json

{
  "status": "running",
  "current_actor_idx": 0,
  "actors": ["prep", "infer", "post"]
}
```

Both progress/status updates and ephemeral FLY events flow through this single
endpoint. **Called by**: sidecars (per-actor status) and `x-sink` / `x-sump`
(final status).

⚠️ **FLY events are ephemeral** — never persisted. Clients connecting after task
completion will NOT see historical FLY events.

#### Get task status

```bash
GET /api/v1/mesh/{id}
```

Response:
```json
{
  "id": "5e6fdb2d-1d6b-4e91-baef-73e825434e7b",
  "status": "succeeded",
  "created_at": "2025-11-18T12:00:00Z",
  "updated_at": "2025-11-18T12:01:30Z",
  "data": {"result": {"response": "Processed: Hello world"}}
}
```

See [Envelope Protocol](../specs/envelope.md) for task statuses.

#### Subscribe to updates (SSE)

```bash
GET /api/v1/mesh/{id}/events
Accept: text/event-stream
```

**Features**:

- Sends historical status updates first (no missed progress)
- Streams real-time updates as they occur
- Relays ephemeral FLY events to connected subscribers
- Keepalive comments every 15 seconds
- Auto-closes on terminal status (`succeeded`, `failed`, `canceled`)

### MCP routes (mcp-adapter, port 8082)

```bash
POST /mcp        # MCP Streamable HTTP transport (recommended)
GET  /mcp/sse    # MCP SSE transport (for clients that require SSE)
GET  /health     # Liveness
```

### A2A routes (a2a-adapter, port 8083)

```bash
POST /a2a/                     # A2A JSON-RPC endpoint
GET  /.well-known/agent.json   # A2A Agent Card (public, no auth)
GET  /health                   # Liveness
```

## Authentication & Security

Authentication is applied per adapter. mesh-api internal routes carry no auth
code — they are protected by network isolation (ClusterIP only).

| Route group | Container | Auth mechanism |
|-------------|-----------|---------------|
| A2A (`/a2a/`) | a2a-adapter | API key (`X-API-Key`) or JWT Bearer — `ASYA_A2A_*` env vars |
| A2A Agent Card + health | a2a-adapter | Always public |
| MCP (`/mcp`, `/mcp/sse`) | mcp-adapter | None currently wired |
| mesh-api (`/api/v1/mesh/…`) | mesh-api | None — internal port is ClusterIP only |

### A2A Authentication

Two schemes are supported with OR semantics — a request is authenticated if
either check passes.

**API Key**

```
X-API-Key: <value>
```

Configured via `ASYA_A2A_API_KEY`. When set, the header value must match exactly.

**JWT Bearer**

```
Authorization: Bearer <JWT>
```

Configured via `ASYA_A2A_JWT_JWKS_URL` + `ASYA_A2A_JWT_ISSUER` +
`ASYA_A2A_JWT_AUDIENCE`. The adapter fetches the JWKS from the configured URL and
validates the token signature, issuer, and audience claims.

When neither `ASYA_A2A_API_KEY` nor `ASYA_A2A_JWT_JWKS_URL` is set, A2A auth is
disabled (all requests pass). This is the default for local development. The
public Agent Card at `/.well-known/agent.json` advertises the configured schemes.

### Mesh Security

The mesh-api internal port (8081) carries no authentication code. Security is
enforced at the network layer:

- `asya-gateway-mesh-api-int` is a `ClusterIP` Service — no Ingress, no NodePort.
  It is physically unreachable from outside the cluster.
- Sidecars and crew actors reach it via in-cluster DNS:
  `asya-gateway-mesh-api-int.<namespace>.svc.cluster.local:8081`.

For defence in depth, add a K8s NetworkPolicy restricting ingress to actor pods,
or enable a service mesh (Istio/Linkerd) for automatic mTLS.

### Environment Variables

Per-component variables are documented in the
[Environment Variables reference](../env-vars.md) — see the `asya-mesh-api`,
`mcp-adapter`, and `a2a-adapter` sections.

## Using MCP tools

**See**: [Quickstart](../../setup/start-quickstart.md) for instructions on testing MCP locally.

## Deployment Helm Charts

**See**: [Gateway Setup Guide](../../setup/guide-gateway.md) for gateway chart details.
