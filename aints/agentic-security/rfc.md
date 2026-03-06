# RFC: Gateway Security Model

**Status**: Draft
**Date**: 2026-03-06
**Epic**: agentic-security
**Related**: a2a-protocol-compliance-gateway (A2A RFC sections 6.1, 12),
asya-lab (flow expose), merged.7fuy (JWT auth)

---

## 1. Summary

This RFC defines the security architecture for asya-gateway. The gateway is
deployed as **two deployment units** from the same binary/image, separating
external (client-facing) and internal (mesh) traffic at the network level.

External routes implement protocol-native authentication: **A2A security
schemes** (API key + JWT, already implemented) and **MCP OAuth 2.1 with PKCE**
(new). Internal mesh routes rely on network isolation with zero auth code.

Flow registration (tool/skill exposure) uses **ConfigMap + kubectl**, inheriting
K8s RBAC for free (see ADR `adr.configmap-flow-registry.md` in
a2a-protocol-compliance-gateway).

---

## 2. Route Groups and Deployment Model

### 2.1 Route Groups

All gateway routes fall into four groups:

| Group | Routes | Audience |
|-------|--------|----------|
| **A2A** | `/a2a/*`, `/.well-known/agent.json` | External AI agents, orchestrators |
| **MCP** | `/mcp`, `/mcp/sse`, `/mcp/tools/call` | LLMs, developers, `asya-lab` CLI |
| **Mesh** | `/mesh/{id}/progress`, `/final`, `/fly`, `/status`, `POST /mesh` | Sidecars, crew actors (internal) |
| **Health** | `/health` | K8s probes, monitoring |

### 2.2 Dual-Deployment Architecture

Same Go binary, mode selected via `ASYA_GATEWAY_MODE` environment variable:

```
ASYA_GATEWAY_MODE=api     serves: /a2a/*, /mcp/*, /.well-known/*, /health
ASYA_GATEWAY_MODE=mesh    serves: /mesh/*, /health
```

| Deployment | Helm release | K8s Service | Ingress | Auth |
|-----------|-------------|-------------|---------|------|
| **asya-gateway-api** | `asya-gateway` (values: `mode: api`) | ClusterIP + Ingress | Yes | Protocol-native |
| **asya-gateway-mesh** | `asya-gateway-mesh` (values: `mode: mesh`) | ClusterIP only | No | Network isolation |

Both deployments share:
- Same container image (`asya-gateway`)
- Same PostgreSQL database (tasks, task_updates)
- Same ConfigMap (`gateway-flows`) for flow/skill registry

### 2.3 Why Dual Deployment

Network-level isolation is stronger than middleware-based auth:
- Misconfigured auth middleware = security hole. Missing Ingress = no exposure.
- Mesh routes have zero auth code surface area — not "auth disabled", but
  **unreachable** from outside the cluster.
- Independent scaling: API scales with client traffic, mesh scales with actor
  count.
- Independent resource limits, health checks, and restart policies.

### 2.4 Implementation

The `main.go` route registration is gated on mode:

```go
mode := os.Getenv("ASYA_GATEWAY_MODE") // "api" or "mesh"

switch mode {
case "api":
    // A2A routes (with auth middleware)
    // MCP routes (with auth middleware)
    // /.well-known/agent.json (public)
    // /health (public)
case "mesh":
    // /mesh/* routes (no auth)
    // /health (public)
default:
    // backward compat: register all routes (dev mode)
}
```

Default mode (empty or unset) registers all routes for backward compatibility
in development and testing.

---

## 3. A2A Authentication

### 3.1 Current State (Already Implemented)

A2A auth is functional with two schemes:

1. **API Key** (`X-API-Key` header) — `ASYA_A2A_API_KEY` env var
2. **JWT/Bearer** (`Authorization: Bearer <token>`) — validates via JWKS

Env vars: `ASYA_A2A_JWT_JWKS_URL`, `ASYA_A2A_JWT_ISSUER`, `ASYA_A2A_JWT_AUDIENCE`

Both use OR semantics — either scheme authenticates the request.

### 3.2 Agent Card Security Declaration

```json
{
  "securitySchemes": {
    "apiKey": {
      "apiKeySecurityScheme": {
        "location": "header",
        "name": "X-API-Key"
      }
    },
    "bearer": {
      "httpAuthSecurityScheme": {
        "scheme": "bearer",
        "bearerFormat": "JWT"
      }
    }
  },
  "security": [
    {"apiKey": {}},
    {"bearer": {}}
  ]
}
```

### 3.3 Public Endpoints

Per A2A spec, `/.well-known/agent.json` is always public (no auth).

### 3.4 Protected Endpoints

All `/a2a/*` routes require authentication when any auth scheme is configured.
If no auth env vars are set, auth is disabled (development mode).

### 3.5 Future: OAuth2 and OIDC

A2A spec supports `OAuth2SecurityScheme` (Client Credentials, Authorization
Code with PKCE, Device Code) and `OpenIdConnectSecurityScheme`. These are
deferred to Phase 4 (Enterprise).

---

## 4. MCP Authentication

### 4.1 Protocol Requirements

MCP specifies OAuth 2.1 with mandatory PKCE (see `research-mcp-auth.md`).
The full flow:

1. Client calls MCP endpoint without token
2. Server returns `401` with `WWW-Authenticate` header
3. Client discovers auth server via `/.well-known/oauth-protected-resource`
   (RFC 9728)
4. Client discovers auth server endpoints via
   `/.well-known/oauth-authorization-server` (RFC 8414)
5. Client optionally registers via Dynamic Client Registration (RFC 7591)
6. Client performs OAuth 2.1 Authorization Code + PKCE flow
7. Client sends Bearer token on subsequent requests

### 4.2 Phased Implementation

#### Phase 2: API Key (Simple, Non-Spec-Compliant)

For internal and trusted clients (`asya-lab` CLI, known MCP hosts):

- Reuse the existing `Authenticator` interface from A2A auth
- Accept `Authorization: Bearer <static-token>` on `/mcp/*` routes
- Env var: `ASYA_MCP_API_KEY`
- When set, `/mcp/*` routes require the key; when empty, auth disabled

This is NOT MCP-spec-compliant but is functional for controlled environments.

#### Phase 3: OAuth 2.1 (Full Spec Compliance)

Gateway implements the MCP authorization server role:

**New endpoints** (on the api deployment):

| Endpoint | Purpose |
|----------|---------|
| `/.well-known/oauth-protected-resource` | RFC 9728 metadata (points to auth server) |
| `/.well-known/oauth-authorization-server` | RFC 8414 server metadata |
| `/oauth/authorize` | Authorization endpoint |
| `/oauth/token` | Token endpoint (code exchange, refresh) |
| `/oauth/register` | Dynamic Client Registration (RFC 7591) |

**Token storage**: PostgreSQL table for issued tokens, refresh tokens, and
registered clients. Lightweight — no external auth server dependency.

**Env vars**:
- `ASYA_MCP_OAUTH_ENABLED` — enable full OAuth 2.1 (default: false)
- `ASYA_MCP_OAUTH_ISSUER` — token issuer URL
- `ASYA_MCP_OAUTH_TOKEN_TTL` — access token lifetime (default: 3600s)

**Scope model** (simple, two scopes):
- `mcp:invoke` — call tools
- `mcp:read` — list tools, read results

**PKCE**: Required for all clients. `code_challenge_method` must be `S256`.

### 4.3 MCP Auth Middleware

Applied to `/mcp`, `/mcp/sse`, `/mcp/tools/call`:

```go
func MCPAuthMiddleware(config MCPAuthConfig) func(http.Handler) http.Handler
```

Supports two modes based on configuration:
- **API key mode** (Phase 2): validates `Authorization: Bearer <static-key>`
- **OAuth mode** (Phase 3): validates JWT Bearer tokens issued by the gateway's
  own token endpoint

---

## 5. Mesh Security

### 5.1 Network Isolation

Mesh routes are protected by network topology, not code:

- `asya-gateway-mesh` Service is ClusterIP (no Ingress, no NodePort)
- Sidecars and crew actors reach it via in-cluster DNS
  (`asya-gateway-mesh.{namespace}.svc.cluster.local`)
- For additional hardening, K8s NetworkPolicy can restrict source pods:

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
              asya.sh/component: actor  # only actor pods
      ports:
        - port: 8080
```

### 5.2 No Auth Code

Zero authentication middleware on mesh routes. The attack surface is the
network boundary, not application code. This eliminates:
- Auth bypass vulnerabilities
- Token management for internal traffic
- Latency from token validation on every sidecar request

### 5.3 Compatibility with asya-lab CLI

The decision to keep mesh routes internal-only has been verified against all
`asya-lab` CLI commands (see asya-lab RFC, section 5.5). No CLI command
requires `/mesh/*` routes:

- **Task invocation/streaming**: uses MCP or A2A protocol endpoints (gateway API)
- **Status, logs, deploy**: uses K8s API (kubectl)
- **Flow exposure**: uses K8s API (kubectl patch ConfigMap)
- **Message trace**: uses OpenTelemetry query API (Jaeger/Tempo)
- **Message replay/inspect/drain**: uses MQ and storage APIs directly

Mesh routes are exclusively for sidecar-to-gateway internal communication.

---

## 6. mTLS and Transport Security (Out of Scope)

Asya does NOT implement mTLS. Transport-level security is a deployment concern
handled by infrastructure. This section documents why and what platform teams
should configure.

### 6.1 Actor-to-Gateway (HTTP)

With dual-deployment, mesh routes are ClusterIP-only — unreachable from outside
the cluster. No application-level auth is needed on mesh routes.

For defense-in-depth, platform teams can enable a service mesh (Istio/Linkerd)
which provides automatic mTLS between all pods with zero Asya code changes.
Alternatively, K8s NetworkPolicy restricts mesh access to actor pods only (see
section 5.1).

### 6.2 Actor-to-Actor (via Message Queue)

Actors never communicate directly. The path is always:

```
Actor A sidecar → MQ (publish) → MQ (consume) → Actor B sidecar
```

Security is handled entirely by the transport layer:

| Transport | Auth | Encryption in transit | Access control |
|-----------|------|----------------------|----------------|
| **SQS** | IAM (IRSA or static creds) | TLS by default (AWS HTTPS endpoints) | IAM policy per queue (`asya-*` prefix) |
| **RabbitMQ** | AMQP credentials (user/pass) | TLS if configured on AMQP listener | Vhost/queue-level permissions |

No application-level mTLS or message signing is needed. The sidecar connects
to the MQ using credentials provided by the deployment (IRSA, K8s Secret, etc.).

### 6.3 What Asya Documents (Not Implements)

- RabbitMQ TLS configuration for AMQP connections
- IAM policy examples for SQS queue-level access control
- Service mesh annotations for automatic mTLS
- K8s NetworkPolicy examples for mesh route restriction

See aint `[1f63]` for the documentation task.

---

## 7. Auth Configuration Summary

| Env Var | Scope | Default | Purpose |
|---------|-------|---------|---------|
| `ASYA_GATEWAY_MODE` | Global | `""` (all routes) | Route group selection |
| `ASYA_A2A_API_KEY` | A2A | `""` (disabled) | API key for A2A |
| `ASYA_A2A_JWT_JWKS_URL` | A2A | `""` (disabled) | JWKS endpoint for JWT |
| `ASYA_A2A_JWT_ISSUER` | A2A | `""` | Expected JWT issuer |
| `ASYA_A2A_JWT_AUDIENCE` | A2A | `""` | Expected JWT audience |
| `ASYA_MCP_API_KEY` | MCP | `""` (disabled) | API key for MCP (Phase 2) |
| `ASYA_MCP_OAUTH_ENABLED` | MCP | `false` | Enable OAuth 2.1 (Phase 3) |
| `ASYA_MCP_OAUTH_ISSUER` | MCP | `""` | OAuth token issuer URL |
| `ASYA_MCP_OAUTH_TOKEN_TTL` | MCP | `3600` | Access token lifetime (s) |

---

## 8. Implementation Phases

### Phase 1: Dual-Deployment Split

Split gateway into two deployment modes. Wire existing A2A auth (API key +
JWT) to the api mode. No new auth code — just route registration gating.

**Scope**:
- Add `ASYA_GATEWAY_MODE` env var and route gating in `main.go`
- Update Helm chart to support two releases (api + mesh)
- Update sidecar `ASYA_GATEWAY_URL` to point to mesh service
- Update integration/e2e tests for dual-deployment
- All existing auth (A2A API key + JWT) works unchanged

### Phase 2: MCP API Key Auth

Simple Bearer token auth for MCP endpoints. Functional for internal use.

**Scope**:
- Add `MCPAuthMiddleware` using existing `Authenticator` interface
- `ASYA_MCP_API_KEY` env var
- Apply to `/mcp`, `/mcp/sse`, `/mcp/tools/call`
- Unit tests for MCP auth

### Phase 3: MCP OAuth 2.1

Full MCP authorization spec compliance.

**Scope**:
- Protected Resource Metadata endpoint (`/.well-known/oauth-protected-resource`)
- Authorization Server Metadata endpoint (`/.well-known/oauth-authorization-server`)
- Authorization endpoint (`/oauth/authorize`)
- Token endpoint (`/oauth/token`) with PKCE validation
- Dynamic Client Registration endpoint (`/oauth/register`)
- PostgreSQL tables for clients, tokens, authorization codes
- Scope-based access control (`mcp:invoke`, `mcp:read`)
- Token refresh and rotation
- MCPAuthMiddleware OAuth mode (validate self-issued JWTs)
- Integration tests with MCP client library

### Phase 4: Enterprise Auth

OAuth2 and OIDC for both protocols.

**Scope**:
- A2A: `OAuth2SecurityScheme` support (Client Credentials flow)
- A2A: `OpenIdConnectSecurityScheme` support
- MCP: Client Credentials grant type (machine-to-machine)
- Scope-based access control for A2A (agent:invoke, agent:read)
- Agent Card dynamically reflects all configured schemes
- Audit logging for auth events

---

## 9. Testing Strategy

### Unit Tests
- Route registration gating per mode
- MCP API key middleware (valid, invalid, missing, disabled)
- MCP OAuth token validation
- PKCE code challenge verification

### Integration Tests
- Dual-deployment with separate services in Docker Compose
- A2A auth flow (API key + JWT) end-to-end
- MCP auth flow (API key) end-to-end

### E2E Tests
- Dual Helm releases in Kind cluster
- Sidecar reaching mesh service, client reaching api service
- NetworkPolicy enforcement (mesh unreachable from outside)

---

## 10. Related Research

- `research-a2a-auth.md` — A2A protocol security specification analysis
- `research-mcp-auth.md` — MCP authorization specification analysis
- `adr.configmap-flow-registry.md` (in a2a-protocol-compliance-gateway) —
  ConfigMap-based flow registration eliminates admin auth requirement

---

## 11. Open Questions

1. **Helm chart structure**: Should the dual deployment use one chart with a
   `mode` value, or two separate charts (`asya-gateway-api`,
   `asya-gateway-mesh`)?

2. **Dev mode**: When `ASYA_GATEWAY_MODE` is empty, all routes are registered
   with no auth. Should dev mode require an explicit `ASYA_GATEWAY_MODE=dev`
   to prevent accidental unprotected production deployments?

3. **MCP OAuth storage**: Should OAuth clients/tokens use the same PostgreSQL
   as tasks, or a separate database? Same DB is simpler; separate DB isolates
   auth state from runtime state.
