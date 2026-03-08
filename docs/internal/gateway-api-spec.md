# Gateway API Specification

Complete reference for all `asya-gateway` HTTP endpoints. Routes are split
across two deployments — see `docs/internal/gateway-security.md` for the
deployment model and auth configuration.

For the A2A and MCP protocol details (JSON-RPC framing, SSE event format, etc.)
see `docs/architecture/asya-gateway.md` and the protocol docs under
`docs/architecture/protocols/`.

---

## Route Map

| Method | Path | Deployment | Auth | Caller |
|--------|------|-----------|------|--------|
| `GET` | `/.well-known/agent.json` | api | Public | External agents |
| `POST` | `/a2a/` | api | A2A auth | External agents |
| `POST` | `/mcp` | api | MCP auth | LLM clients, asya-lab |
| `GET` | `/mcp/sse` | api | MCP auth | LLM clients, asya-lab |
| `POST` | `/tools/call` | api | MCP auth | LLM clients, asya-lab |
| `GET` | `/.well-known/oauth-protected-resource` | api | Public | MCP clients |
| `GET` | `/.well-known/oauth-authorization-server` | api | Public | MCP clients |
| `POST` | `/oauth/register` | api | Open or token | MCP clients |
| `GET` | `/oauth/authorize` | api | Public | MCP clients |
| `POST` | `/oauth/token` | api | Public | MCP clients |
| `POST` | `/mesh` | mesh | Network isolation | Sidecar (fanout) |
| `GET` | `/mesh/{id}` | mesh | Network isolation | Sidecar, asya-cli |
| `GET` | `/mesh/{id}/stream` | mesh | Network isolation | Sidecar, asya-cli |
| `GET` | `/mesh/{id}/active` | mesh | Network isolation | Sidecar |
| `POST` | `/mesh/{id}/progress` | mesh | Network isolation | Sidecar |
| `POST` | `/mesh/{id}/final` | mesh | Network isolation | x-sink, x-sump |
| `POST` | `/mesh/{id}/fly` | mesh | Network isolation | Sidecar (FLY events) |
| `GET` | `/mesh/expose` | mesh | Optional API key | Sidecar |
| `POST` | `/mesh/expose` | mesh | Optional API key | Sidecar |
| `GET` | `/health` | api + mesh | Public | K8s probes |

---

## External API Routes (api deployment)

### A2A Protocol

#### `GET /.well-known/agent.json`

Returns the public Agent Card. Unauthenticated — required by the A2A spec for
discovery.

**Response** `200 application/json`:
```json
{
  "name": "asya-gateway",
  "version": "1.0.0",
  "supportedInterfaces": [{
    "url": "https://gateway.example.com/a2a/v1",
    "protocolBinding": "JSONRPC",
    "protocolVersion": "1.0"
  }],
  "capabilities": {
    "streaming": true,
    "extendedAgentCard": true
  },
  "securitySchemes": {
    "apiKey": { "apiKeySecurityScheme": { "location": "header", "name": "X-API-Key" } },
    "bearer": { "httpAuthSecurityScheme": { "scheme": "bearer", "bearerFormat": "JWT" } }
  },
  "security": [{ "apiKey": {} }, { "bearer": {} }],
  "skills": [...]
}
```

---

#### `POST /a2a/`

A2A JSON-RPC 2.0 endpoint. All A2A operations use this single endpoint.
Requires authentication when any A2A auth env var is set.

**Request** `application/json` — JSON-RPC 2.0 envelope:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "message/send",
  "params": { ... }
}
```

Supported methods: `message/send`, `message/stream`, `tasks/get`, `tasks/list`,
`tasks/cancel`, `tasks/resubscribe`, `agent/authenticatedExtendedCard`,
`pushNotification/set`, `pushNotification/get`, `pushNotification/list`,
`pushNotification/delete`.

**Response** `200 application/json` — JSON-RPC 2.0 response:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": { ... }
}
```

**Auth errors** `401` — missing/invalid credentials.

---

### MCP Protocol

#### `POST /mcp`

MCP Streamable HTTP transport. Accepts MCP JSON-RPC 2.0 requests. The
`mark3labs/mcp-go` library handles protocol framing.

**Request** `application/json`:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "my-tool",
    "arguments": { "key": "value" }
  }
}
```

Common methods: `initialize`, `tools/list`, `tools/call`.

**Response** `200 application/json` — MCP JSON-RPC 2.0 response.

**Auth** — Bearer token required when `ASYA_MCP_API_KEY` or
`ASYA_MCP_OAUTH_ENABLED=true` is configured. Returns `401` with
`WWW-Authenticate: Bearer` on failure.

---

#### `GET /mcp/sse`

MCP SSE transport. Establishes a persistent SSE connection for MCP session
management. Use for clients that require SSE-based MCP sessions.

**Response** `200 text/event-stream` — SSE stream of MCP protocol messages.

**Auth** — same as `POST /mcp`.

---

#### `POST /tools/call`

REST convenience wrapper for MCP tool invocation. Simpler than the full MCP
protocol; does not require session management.

**Request** `application/json`:
```json
{
  "name": "text-processor",
  "arguments": {
    "text": "hello world",
    "model": "gpt-4"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Tool name as registered |
| `arguments` | object | No | Tool-specific input parameters |

**Response** `200 application/json` — MCP `CallToolResult`:
```json
{
  "content": [
    {
      "type": "text",
      "text": "{\"task_id\":\"5e6fdb2d\",\"status_url\":\"/mesh/5e6fdb2d\"}"
    }
  ],
  "isError": false
}
```

**Error responses**:
- `400` — missing `name` field or invalid JSON
- `404` — tool not found in registry
- `500` — tool handler failed

**Auth** — same as `POST /mcp`.

---

### OAuth 2.1 Endpoints

Only registered when `ASYA_MCP_OAUTH_ENABLED=true`. All public (called before
auth is established). See `docs/internal/gateway-security.md` §4 for the full
OAuth 2.1 flow.

#### `GET /.well-known/oauth-protected-resource`

RFC 9728 Protected Resource Metadata. Points MCP clients to the authorization
server.

**Response** `200 application/json`:
```json
{
  "resource": "https://gateway.example.com",
  "authorization_servers": ["https://gateway.example.com"]
}
```

---

#### `GET /.well-known/oauth-authorization-server`

RFC 8414 Authorization Server Metadata. Exposes all OAuth endpoint URLs and
capabilities.

**Response** `200 application/json`:
```json
{
  "issuer": "https://gateway.example.com",
  "authorization_endpoint": "https://gateway.example.com/oauth/authorize",
  "token_endpoint": "https://gateway.example.com/oauth/token",
  "registration_endpoint": "https://gateway.example.com/oauth/register",
  "scopes_supported": ["mcp:invoke", "mcp:read"],
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "code_challenge_methods_supported": ["S256"],
  "token_endpoint_auth_methods_supported": ["none"]
}
```

---

#### `POST /oauth/register`

RFC 7591 Dynamic Client Registration. Registers a new OAuth client.

Optionally protected by `ASYA_MCP_OAUTH_REGISTRATION_TOKEN` — when set,
requires `Authorization: Bearer <registration-token>`.

**Request** `application/json`:
```json
{
  "client_name": "My MCP Client",
  "redirect_uris": ["http://localhost:3000/callback"],
  "scope": "mcp:invoke mcp:read"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `redirect_uris` | string[] | Yes | Allowed redirect URIs (localhost or HTTPS) |
| `client_name` | string | No | Human-readable client name |
| `scope` | string | No | Requested scopes; defaults to all supported |

**Response** `201 application/json`:
```json
{
  "client_id": "b3e7f9a2-...",
  "client_name": "My MCP Client",
  "redirect_uris": ["http://localhost:3000/callback"],
  "scope": "mcp:invoke mcp:read"
}
```

**Error responses**:
- `400` — missing `redirect_uris` or invalid JSON
- `401` — registration token required but missing/wrong

---

#### `GET /oauth/authorize`

Authorization Code endpoint. Auto-approves registered public clients (no user
login UI — gateway is designed for machine-to-machine flows). PKCE `S256` is
required.

**Query parameters**:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `client_id` | Yes | Registered client ID |
| `redirect_uri` | Yes | Must match a registered URI |
| `response_type` | Yes | Must be `code` |
| `code_challenge` | Yes | PKCE S256 challenge (base64url of SHA-256 of verifier) |
| `code_challenge_method` | Yes | Must be `S256` |
| `scope` | No | Requested scopes; defaults to client's registered scopes |
| `state` | No | Opaque value echoed back to redirect URI |

**Response** `302 Found` — redirect to `redirect_uri?code=<code>&state=<state>`.

Authorization codes expire after 5 minutes and are single-use.

**Error responses** (400 JSON body):
- `unsupported_response_type` — only `code` is supported
- `invalid_request` — missing `code_challenge` or wrong method
- `invalid_client` — unknown `client_id`
- `invalid_request` — `redirect_uri` not registered
- `invalid_scope` — requested scopes not in client's registered set

---

#### `POST /oauth/token`

Token exchange and refresh.

**Request** `application/x-www-form-urlencoded`

**Authorization Code exchange**:

| Field | Required | Description |
|-------|----------|-------------|
| `grant_type` | Yes | `authorization_code` |
| `code` | Yes | Code from `/oauth/authorize` redirect |
| `client_id` | Yes | Registered client ID |
| `redirect_uri` | Yes | Must match the URI used in the auth request |
| `code_verifier` | Yes | PKCE verifier (raw random string, SHA-256 matches challenge) |

**Refresh Token**:

| Field | Required | Description |
|-------|----------|-------------|
| `grant_type` | Yes | `refresh_token` |
| `refresh_token` | Yes | Token from previous response |
| `client_id` | Yes | Registered client ID |

**Response** `200 application/json`:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "dGhpcyBpcyBhIHJlZnJl...",
  "scope": "mcp:invoke mcp:read"
}
```

Access tokens are HMAC-SHA256 JWTs containing `iss`, `aud`, `sub` (client ID),
`scope`, `iat`, `exp`, `jti` claims. Refresh tokens are opaque, stored hashed
in PostgreSQL, and rotated on each use (old token revoked, new token issued).

**Error responses** (400 JSON body):
- `invalid_grant` — code expired/used, verifier mismatch, or refresh token
  invalid/revoked
- `invalid_grant` — `client_id` or `redirect_uri` mismatch
- `unsupported_grant_type` — only `authorization_code` and `refresh_token`

---

### Health

#### `GET /health`

**Response** `200 text/plain`:
```
OK
```

---

## Mesh Routes (mesh deployment)

Called exclusively by sidecars and crew actors within the cluster. No
authentication code — unreachable externally by network topology.

### Task Lifecycle

#### `POST /mesh`

Creates a fanout child task. Called by the sidecar when the runtime returns an
array response, triggering fan-out to parallel actor pipelines.

**Request** `application/json`:
```json
{
  "id": "task-abc-1",
  "parent_id": "task-abc",
  "prev": ["actor-a"],
  "curr": "actor-b",
  "next": ["actor-c", "actor-d"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Task ID (must be unique) |
| `parent_id` | string | No | Original task ID for traceability |
| `prev` | string[] | No | Already-processed actors |
| `curr` | string | No | Currently-processing actor |
| `next` | string[] | No | Remaining actors in pipeline |

**Response** `201 application/json`:
```json
{ "status": "created", "id": "task-abc-1" }
```

---

#### `GET /mesh/{id}`

Returns full task state.

**Response** `200 application/json` — `Task` object:
```json
{
  "id": "task-abc",
  "parent_id": null,
  "context_id": "ctx-xyz",
  "status": "running",
  "route": { "prev": ["actor-a"], "curr": "actor-b", "next": ["actor-c"] },
  "payload": { ... },
  "result": null,
  "progress_percent": 33.0,
  "current_actor_name": "actor-b",
  "message": "actor-b: processing",
  "actors_completed": 1,
  "total_actors": 3,
  "created_at": "2026-03-08T10:00:00Z",
  "updated_at": "2026-03-08T10:00:05Z"
}
```

**Task status values**: `pending`, `running`, `succeeded`, `failed`, `paused`,
`canceled`, `auth_required`.

**Error** `404` — task not found.

---

#### `GET /mesh/{id}/stream`

SSE stream of task update events. Replays historical updates first (no missed
progress), then streams live updates. Sends keepalive comments every 15 seconds.
Closes when task reaches a final status.

**Response** `200 text/event-stream`:

Progress update event:
```
event: update
data: {"id":"task-abc","status":"running","progress_percent":33.0,"curr":"actor-b","task_state":"processing","message":"actor-b: processing","timestamp":"2026-03-08T10:00:05Z"}

```

Partial payload event (FLY — e.g. LLM token stream):
```
event: text_delta
data: {"type":"text_delta","token":"Hello"}

```

Keepalive:
```
: keepalive

```

Final event (closes stream):
```
event: update
data: {"id":"task-abc","status":"succeeded","progress_percent":100,"result":{...},"timestamp":"2026-03-08T10:01:00Z"}

```

**Error** `404` — task not found.

---

#### `GET /mesh/{id}/active`

Allows sidecars to check whether a task is still accepting progress updates
(i.e., has not timed out or completed). Called before sending each message to
the runtime.

**Response** `200 application/json` — task is active:
```json
{ "active": true }
```

**Response** `410 Gone application/json` — task timed out or completed:
```json
{ "active": false }
```

---

#### `POST /mesh/{id}/progress`

Reports per-actor progress. Called by the sidecar at three checkpoints per actor:
`received` → `processing` → `completed`. Progress percentage is calculated by
the gateway and enforced monotonically (never decreases).

**Progress formula**: `(len(prev) + status_weight) × 100 / total_actors`

| Actor state | `status_weight` |
|-------------|----------------|
| `received` | 0.1 |
| `processing` | 0.5 |
| `completed` | 1.0 |

**Request** `application/json`:
```json
{
  "prev": ["actor-a"],
  "curr": "actor-b",
  "next": ["actor-c"],
  "status": "processing",
  "message": "actor-b: processing input"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prev` | string[] | Yes | Completed actors (may be modified by ABI) |
| `curr` | string | Yes | Current actor (`""` at end-of-route) |
| `next` | string[] | Yes | Remaining actors (may be modified by ABI) |
| `status` | string | Yes | `received` \| `processing` \| `completed` |
| `message` | string | No | Human-readable status message |
| `pause_metadata` | object | No | Present when actor yields `x-asya-pause` |

**Response** `200 application/json`:
```json
{ "status": "ok", "progress_percent": 38.3 }
```

**Notes**:
- Unknown task IDs return `200 OK` silently — expected for direct-SQS envelopes
  that bypass gateway task creation.
- When `pause_metadata` is present, task transitions to `paused` status.
- Route fields (`prev`/`curr`/`next`) may differ from the original if actors
  modified routing via ABI `SET` yields.

---

#### `POST /mesh/{id}/final`

Reports final task status. Called by `x-sink` (on success) or `x-sump` (on
failure) after the full pipeline has completed.

**Request** `application/json`:
```json
{
  "id": "task-abc",
  "status": "succeeded",
  "result": { "output": "processed text" },
  "current_actor_name": "x-sink",
  "metadata": { "s3_uri": "s3://bucket/task-abc/result.json" }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | No | Task ID (overridden by path param) |
| `status` | string | Yes | `succeeded` or `failed` |
| `result` | any | No | Final result payload |
| `error` | string | No | Error message (for `failed`) |
| `error_details` | any | No | Structured error details (stored in `result`) |
| `current_actor_name` | string | No | Which actor produced the final status |
| `metadata` | object | No | Extra metadata; `s3_uri` appended to success message |

**Response** `200 application/json`:
```json
{ "status": "ok" }
```

**Error** `400` — `status` is not `succeeded` or `failed`.

---

#### `POST /mesh/{id}/fly`

Forwards FLY (partial payload) events from the sidecar to SSE clients. FLY
events carry incremental results from generator handlers (e.g., LLM token
streams) and bypass the message queue entirely.

Body is limited to 1 MiB.

**Request** `application/json` — arbitrary JSON, passed through verbatim:
```json
{ "type": "text_delta", "token": "Hello" }
```

The event type used in the SSE stream is derived from the `type` field if
present, otherwise defaults to `partial`.

**Response** `200` — empty body.

**Error** `413` — body exceeds 1 MiB.

---

### Tool Registry

#### `GET /mesh/expose`

Lists all currently registered tools from the DB-backed registry.

**Response** `200 application/json` — array of `Tool` objects:
```json
[
  {
    "name": "text-processor",
    "actor": "preprocess",
    "route_next": ["llm-infer", "postprocess"],
    "description": "Process text with LLM pipeline",
    "parameters": { "type": "object", "properties": { "text": { "type": "string" } }, "required": ["text"] },
    "timeout_sec": 120,
    "progress": true,
    "mcp_enabled": true,
    "a2a_enabled": false,
    "created_at": "2026-03-08T09:00:00Z",
    "updated_at": "2026-03-08T09:00:00Z"
  }
]
```

**Auth** — protected by `ASYA_A2A_API_KEY` when configured.

---

#### `POST /mesh/expose`

Registers or updates a tool in the DB-backed registry. Called by sidecars or
deployment tooling to expose actor pipelines as MCP tools or A2A skills.

Returns `201 Created` for new tools, `200 OK` for updates.

**Request** `application/json`:
```json
{
  "name": "text-processor",
  "actor": "preprocess",
  "route": ["preprocess", "llm-infer", "postprocess"],
  "description": "Process text with LLM pipeline",
  "parameters": {
    "type": "object",
    "properties": {
      "text": { "type": "string", "description": "Input text" },
      "model": { "type": "string", "enum": ["gpt-4", "gpt-3.5-turbo"], "default": "gpt-4" }
    },
    "required": ["text"]
  },
  "timeout_sec": 120,
  "progress": true,
  "mcp_enabled": true,
  "a2a": {
    "enabled": true,
    "tags": ["nlp", "text"],
    "input_modes": ["text/plain"],
    "output_modes": ["text/plain"]
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique tool identifier |
| `actor` | string | Yes\* | First actor in the pipeline (`*` or use `route`) |
| `route` | string[] | Yes\* | Full pipeline; `actor` = `route[0]`, `route_next` = `route[1:]` |
| `description` | string | No | Human-readable description shown in MCP tool list |
| `parameters` | JSON Schema | No | Input schema for the tool |
| `timeout_sec` | int | No | Per-invocation timeout in seconds |
| `progress` | bool | No | Whether the tool emits progress events |
| `mcp_enabled` | bool | No | Expose via MCP protocol (default: `true`) |
| `a2a` | object | No | A2A skill configuration |
| `a2a.enabled` | bool | No | Expose as A2A skill |
| `a2a.tags` | string[] | No | Tags for A2A skill discovery |
| `a2a.input_modes` | string[] | No | MIME types accepted (e.g., `text/plain`) |
| `a2a.output_modes` | string[] | No | MIME types produced |

\* Either `actor` or `route` must be present. If both, `route` takes precedence.

**Response** `201` or `200 application/json` — registered `Tool` object.

**Auth** — protected by `ASYA_A2A_API_KEY` when configured.

---

## Common Error Formats

### Standard HTTP errors (non-OAuth, non-A2A routes)

Plain text body, e.g.:
```
Method not allowed
```
```
Invalid request body
```
```
Task not found
```

### OAuth errors

`application/json` body conforming to RFC 6749 §5.2:
```json
{
  "error": "invalid_grant",
  "error_description": "code_verifier does not match challenge"
}
```

### MCP/A2A errors

JSON-RPC 2.0 error envelope:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": { "code": -32601, "message": "Method not found" }
}
```

Auth failures on MCP routes return `401` with header:
```
WWW-Authenticate: Bearer realm="asya-gateway"
```

---

## Known Gaps (post-v0)

- **OpenAPI spec**: No machine-readable OpenAPI spec is served or generated.
  See aint `[docs/…]` for tracking. Serving `/openapi.json` would enable
  auto-generated client SDKs and interactive documentation.
- **OAuth scope enforcement**: Tokens carry `mcp:invoke`/`mcp:read` scope
  claims but scopes are not checked per-endpoint. See aint `[misc/wkv3]`.
- **`/a2a/` endpoint detail**: A2A JSON-RPC methods are delegated to the
  `a2asrv` library. Full method-level documentation lives in
  `docs/architecture/protocols/`.
