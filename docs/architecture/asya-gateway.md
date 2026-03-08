# Asya Gateway

## Responsibilities

- Expose MCP-compliant HTTP API
- Create tasks from HTTP requests
- Track task status in PostgreSQL
- Stream progress updates via Server-Sent Events (SSE)
- Receive status reports from crew actors

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

Both releases share the same container image and PostgreSQL database. Sidecars
and crew actors reach the mesh deployment via in-cluster DNS:
`asya-gateway-mesh.<namespace>.svc.cluster.local`.

**Gateway is stateful**: Requires PostgreSQL database for task tracking and
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

Tool/skill registration is **DB-backed**: tools are registered dynamically via
the tool store API, not via static YAML. See `src/asya-gateway/config/README.md`
for the complete configuration reference.

**See also**: `docs/internal/gateway-security.md` for all auth-related env vars
(`ASYA_A2A_API_KEY`, `ASYA_MCP_OAUTH_*`, etc.).

## API Endpoints

**See**: `docs/internal/gateway-api-spec.md` for the full API reference with complete request/response schemas for all routes.



Routes are split across the two deployments. Authentication requirements are
described in `docs/internal/gateway-security.md`.

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

See [Actor-Actor Protocol](protocols/actor-actor.md#task-status-tracking) for more details on task statuses.

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

**Features**:

- Sends historical updates first (no missed progress)
- Streams real-time updates as they occur
- Keepalive comments every 15 seconds
- Auto-closes on final status (`succeeded` or `failed`)

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

## Tool Examples

**Simple tool**:
```yaml
- name: hello
  description: Say hello
  parameters:
    who:
      type: string
      required: true
  route: [hello-actor]
```

**Multi-step pipeline**:
```yaml
- name: image-enhance
  description: Enhance image quality
  parameters:
    image_url:
      type: string
      required: true
    quality:
      type: string
      enum: [low, medium, high]
      default: medium
  route: [download-image, enhance, upload]
```

**Complex parameters**:
```yaml
- name: llm-pipeline
  description: Multi-step LLM processing
  parameters:
    prompt:
      type: string
      required: true
    config:
      type: object
      properties:
        temperature:
          type: number
          default: 0.7
        max_tokens:
          type: integer
          default: 1000
  route: [validate, llm-infer, postprocess]
```

## Security

The gateway implements protocol-native authentication on external routes and
network-level isolation for mesh routes. No auth code runs on mesh routes —
they are unreachable from outside the cluster by design.

| Route group | Auth mechanism |
|-------------|---------------|
| A2A (`/a2a/`) | API key (`X-API-Key`) or JWT Bearer — configured via `ASYA_A2A_*` env vars |
| MCP (`/mcp`, `/mcp/sse`, `/tools/call`) | API key Bearer or OAuth 2.1 token — configured via `ASYA_MCP_*` env vars |
| Mesh (`/mesh/…`) | None — ClusterIP only, unreachable externally |
| Well-known + health | Always public |

OAuth 2.1 tokens carry `mcp:invoke` / `mcp:read` scope claims; per-endpoint
scope enforcement is post-v0 (tokens are authenticated but scopes are not yet
checked per operation).

**See**: `docs/internal/gateway-security.md` for the complete security reference:
deployment model rationale, env var table, OAuth 2.1 flow walkthrough, and
NetworkPolicy examples.

## Using MCP tools
**See**: [For Data Scientists](../quickstart/for-data-scientists.md#using-mcp-tools) for instructions how to test MCP locally.

## Deployment Helm Charts

**See**: [../install/helm-charts.md](../install/helm-charts.md) for gateway chart details.
