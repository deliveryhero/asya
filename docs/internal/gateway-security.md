# Gateway Security Model

**Status**: Implemented (Phases 1–3)
**Source**: `.aint/aints/agentic-security/rfc.md`

This document describes the security architecture of `asya-gateway` as
implemented. It is the authoritative reference for contributors and operators.
For the original design rationale see the RFC; for protocol-level spec details
see `research-a2a-auth.md` and `research-mcp-auth.md` in the same aint.

---

## 1. Deployment Model

The gateway binary is deployed in one of three modes controlled by
`ASYA_GATEWAY_MODE`:

| Mode | Routes registered | Use |
|------|------------------|-----|
| `api` | A2A + MCP + OAuth + health | External-facing deployment; behind Ingress |
| `mesh` | Mesh + health | Internal-facing; ClusterIP only, no Ingress |
| `testing` | All routes | Local development and integration tests |

Empty or unrecognised values cause the process to exit at startup with an error.

### Typical production setup

Two Helm releases from the same `asya-gateway` chart:

```
asya-gateway       (mode: api)   — ClusterIP + Ingress, internet-reachable
asya-gateway-mesh  (mode: mesh)  — ClusterIP only, cluster-internal
```

Both releases share:
- The same container image
- The same PostgreSQL database (`ASYA_DATABASE_URL`)
- The same tool registry (backed by the same DB)

### Why two deployments instead of a middleware flag

Network-level isolation is stronger than auth middleware: a misconfigured
middleware is a security hole; a missing Ingress means the route is physically
unreachable. Mesh routes have zero auth code surface area — they are
unreachable from outside the cluster, not "auth disabled".

---

## 2. Route Reference

### API deployment routes (`ASYA_GATEWAY_MODE=api`)

| Path | Auth | Description |
|------|------|-------------|
| `GET /.well-known/agent.json` | Public | A2A Agent Card discovery |
| `POST /a2a/` | A2A auth | A2A JSON-RPC (message/send, tasks/get, …) |
| `GET /mcp/sse` | MCP auth | MCP SSE transport |
| `POST /mcp` | MCP auth | MCP Streamable HTTP transport |
| `POST /tools/call` | MCP auth | MCP tool invocation (legacy path) |
| `GET /health` | Public | Liveness/readiness probe |

OAuth endpoints (registered when `ASYA_MCP_OAUTH_ENABLED=true`):

| Path | Auth | Description |
|------|------|-------------|
| `GET /.well-known/oauth-protected-resource` | Public | RFC 9728 resource metadata |
| `GET /.well-known/oauth-authorization-server` | Public | RFC 8414 server metadata |
| `POST /oauth/register` | Open or token-gated | Dynamic Client Registration (RFC 7591) |
| `GET/POST /oauth/authorize` | Public | Authorization Code endpoint |
| `POST /oauth/token` | Public | Token exchange and refresh |

### Mesh deployment routes (`ASYA_GATEWAY_MODE=mesh`)

| Path | Auth | Description |
|------|------|-------------|
| `POST /mesh` | Network isolation | Create task from sidecar |
| `POST /mesh/expose` | Network isolation | Expose flow route (SSE) |
| `GET /mesh/{id}/…`  | Network isolation | Per-task status, stream, and active check |
| `POST /mesh/{id}/…` | Network isolation | Per-task progress, final status, and fly events |
| `GET /health` | Public | Liveness/readiness probe |

> **Note on A2A discovery path**: The `a2asrv` library registers the Agent Card
> at `/.well-known/agent.json`. Newer A2A spec drafts use
> `/.well-known/agent-card.json`. We follow what the library provides; both
> path variants are equivalent in intent.

---

## 3. A2A Authentication

### Schemes

Two schemes are supported with OR semantics — a request is authenticated if
either check passes:

**Scheme 1 — API Key**

```
X-API-Key: <value>
```

Configured via `ASYA_A2A_API_KEY`. When set, the header value must match
exactly (constant-time comparison).

**Scheme 2 — JWT Bearer**

```
Authorization: Bearer <JWT>
```

Configured via `ASYA_A2A_JWT_JWKS_URL` + `ASYA_A2A_JWT_ISSUER` +
`ASYA_A2A_JWT_AUDIENCE`. The gateway fetches the JWKS from the configured URL
and validates the token signature, issuer, and audience claims.

### Auth disabled

When neither `ASYA_A2A_API_KEY` nor `ASYA_A2A_JWT_JWKS_URL` is set, A2A auth
is disabled (all requests pass). This is the default for local development.

### Agent Card security declaration

The public Agent Card at `/.well-known/agent.json` advertises the configured
schemes:

```json
{
  "securitySchemes": {
    "apiKey": {
      "apiKeySecurityScheme": { "location": "header", "name": "X-API-Key" }
    },
    "bearer": {
      "httpAuthSecurityScheme": { "scheme": "bearer", "bearerFormat": "JWT" }
    }
  },
  "security": [
    { "apiKey": {} },
    { "bearer": {} }
  ]
}
```

`/.well-known/agent.json` is always public — the A2A spec requires unauthenticated
Agent Card access for discovery.

### Task isolation

Authenticated clients access only their own tasks. The gateway must not reveal
the existence of tasks belonging to other clients (no 404 vs 403 leak).

---

## 4. MCP Authentication

MCP auth is applied to `/mcp`, `/mcp/sse`, and `/tools/call` via
`MCPAuthMiddleware`. Two modes are mutually exclusive:

### Phase 2 — API key (simple, non-spec-compliant)

```
Authorization: Bearer <static-key>
```

Set `ASYA_MCP_API_KEY` to a shared secret. Suitable for internal tooling
(`asya-lab` CLI, known MCP hosts) where full OAuth is not needed.

When `ASYA_MCP_API_KEY` is empty, MCP auth is disabled.

### Phase 3 — OAuth 2.1 (full MCP spec compliance)

Set `ASYA_MCP_OAUTH_ENABLED=true` plus `ASYA_MCP_OAUTH_ISSUER` and
`ASYA_MCP_OAUTH_SECRET`. The gateway acts as its own authorization server,
issuing HMAC-SHA256 JWTs. PostgreSQL is required (`ASYA_DATABASE_URL`).

**Scopes (issued but not yet enforced per-endpoint):**

| Scope | Intended permission |
|-------|-------------------|
| `mcp:invoke` | Call tools, send messages |
| `mcp:read` | List tools, read task state |

Scopes are issued into access tokens and stored in the database. However,
`MCPAuthMiddleware` currently only validates that a token is authentic (signature,
`iss`, `aud`, `exp`) — it does **not** check that the token's scope is sufficient
for the specific operation being requested. A token with only `mcp:read` scope
can currently invoke tools.

> **Post-v0**: Per-endpoint scope enforcement requires extending the
> `Authenticator` interface to return claims (not just a boolean), then adding
> scope guards per route. Tracked separately.

**Token validation**: `OAuthBearerAuthenticator` verifies HMAC-SHA256 signature,
`iss` and `aud` claims, and token expiry against the configured issuer.

#### Full OAuth 2.1 flow

```
Client                     Gateway (api)
  |                              |
  |  GET /mcp (no token)         |
  |----------------------------->|
  |  401 WWW-Authenticate:       |
  |  Bearer resource_metadata=…  |
  |<-----------------------------|
  |                              |
  |  GET /.well-known/oauth-protected-resource
  |----------------------------->|
  |  { authorization_servers: [issuer] }
  |<-----------------------------|
  |                              |
  |  GET /.well-known/oauth-authorization-server
  |----------------------------->|
  |  { authorization_endpoint, token_endpoint, … }
  |<-----------------------------|
  |                              |
  |  POST /oauth/register        |
  |  { client_name, redirect_uris, grant_types }
  |----------------------------->|
  |  { client_id }               |
  |<-----------------------------|
  |                              |
  |  GET /oauth/authorize?       |
  |    client_id=…&              |
  |    code_challenge=…(S256)    |
  |----------------------------->|
  |  302 → redirect_uri?code=…   |
  |<-----------------------------|
  |                              |
  |  POST /oauth/token           |
  |  grant_type=authorization_code
  |  code=…&code_verifier=…      |
  |----------------------------->|
  |  { access_token, refresh_token, expires_in }
  |<-----------------------------|
  |                              |
  |  POST /mcp                   |
  |  Authorization: Bearer <JWT> |
  |----------------------------->|
  |  200 OK                      |
  |<-----------------------------|
```

PKCE (`code_challenge_method=S256`) is required for all clients.

#### Dynamic Client Registration

`/oauth/register` is public by default. To restrict it, set
`ASYA_MCP_OAUTH_REGISTRATION_TOKEN` — callers must then supply
`Authorization: Bearer <registration-token>` to register. Leave empty only for
local development or if the `api` deployment is in a trusted, network-restricted environment.

> **Note on test coverage**: The component test (`testing/component/gateway-mcp`)
> covers the API key auth path (Phase 2) but not the full OAuth 2.1 flow.
> Integration tests exercising the complete register → authorize → token → MCP
> call sequence are post-v0.

#### Token refresh

`POST /oauth/token` with `grant_type=refresh_token` exchanges a refresh token
for a new access+refresh token pair. Refresh tokens are stored in PostgreSQL
(`oauth_tokens` table) with a default 30-day TTL.

---

## 5. Mesh Security

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
all pods with zero Asya code changes. See aint `[1f63]` for documentation on
both options.

---

## 6. Environment Variable Reference

All auth-related env vars. Non-auth vars (`ASYA_NAMESPACE`, transport URLs,
etc.) are documented in `docs/architecture/asya-gateway.md`.

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

---

## 7. Local Development

Use `ASYA_GATEWAY_MODE=testing` to run a single gateway process with all routes
registered (API + mesh). This is how integration and component tests run the
gateway.

Minimal config with no auth:

```bash
ASYA_GATEWAY_MODE=testing \
ASYA_DATABASE_URL=postgres://... \
./asya-gateway
```

To test MCP API key auth locally:

```bash
ASYA_GATEWAY_MODE=testing \
ASYA_MCP_API_KEY=dev-secret \
./asya-gateway
# then: curl -H "Authorization: Bearer dev-secret" http://localhost:8080/mcp
```

To test full OAuth 2.1 locally, PostgreSQL is required:

```bash
ASYA_GATEWAY_MODE=testing \
ASYA_DATABASE_URL=postgres://localhost/asya \
ASYA_MCP_OAUTH_ENABLED=true \
ASYA_MCP_OAUTH_ISSUER=http://localhost:8080 \
ASYA_MCP_OAUTH_SECRET=a-32-byte-secret-for-local-dev!! \
./asya-gateway
```

The gateway will auto-approve authorization requests (no login UI — machine-to-machine
design). Register a client, obtain a code via `/oauth/authorize`, exchange it at
`/oauth/token`, and use the returned JWT as `Authorization: Bearer <token>`.

---

## 8. PostgreSQL Schema

OAuth 2.1 uses three tables in the same database as the task store:

| Table | Contents |
|-------|---------|
| `oauth_clients` | Registered client IDs, redirect URIs, scopes |
| `oauth_authorization_codes` | Short-lived authorization codes (PKCE challenge stored) |
| `oauth_tokens` | Refresh tokens (access tokens are stateless JWTs) |

Migrations run automatically at startup when `ASYA_MCP_OAUTH_ENABLED=true`.

---

## 9. Related Documents

| Document | Location |
|----------|---------|
| Gateway architecture | `docs/architecture/asya-gateway.md` |
| A2A protocol security spec | `.aint/aints/agentic-security/research-a2a-auth.md` |
| MCP authorization spec | `.aint/aints/agentic-security/research-mcp-auth.md` |
| Security model RFC | `.aint/aints/agentic-security/rfc.md` |
| TLS/mTLS deployment guidance | `.aint/aints/agentic-security/backlog.1f63…` (post-v0) |
