---
description: "Gateway setup: deploy api/mesh modes, configure auth, PostgreSQL, register MCP tools, A2A agents"
---

# Gateway

This guide shows how to deploy and configure the Asya gateway, including authentication, tool registration, and multi-mode deployment.

## Prerequisites

- Kubernetes cluster with kubectl access
- Helm 3.0+
- PostgreSQL database (for OAuth 2.1 and task state)

## Deployment Model

The gateway binary is deployed in one of three modes controlled by `ASYA_GATEWAY_MODE`:

| Mode | Routes registered | Use |
|------|------------------|-----|
| `api` | A2A + MCP + OAuth + health | External-facing deployment; behind Ingress |
| `mesh` | Mesh + health | Internal-facing; ClusterIP only, no Ingress |
| `testing` | All routes | Local development and integration tests |

Empty or unrecognised values cause the process to exit at startup with an error.

### Typical Production Setup

Two Helm releases from the same `asya-gateway` chart:

```
asya-gateway       (mode: api)   — ClusterIP + Ingress, internet-reachable
asya-gateway-mesh  (mode: mesh)  — ClusterIP only, cluster-internal
```

Both releases share:
- The same container image
- The same PostgreSQL database (`ASYA_DATABASE_URL`)
- The same tool registry (backed by the same DB)

### Why Two Deployments

Network-level isolation is stronger than auth middleware: a misconfigured middleware is a security hole; a missing Ingress means the route is physically unreachable. Mesh routes have zero auth code surface area — they are unreachable from outside the cluster, not "auth disabled".

## Step 1: Install PostgreSQL

The gateway requires PostgreSQL for task state storage and OAuth 2.1 (if enabled).

```bash
helm upgrade --install asya-gateway-postgresql oci://registry-1.docker.io/bitnamicharts/postgresql \
  --namespace asya-system --create-namespace \
  --set auth.database=asya_gateway \
  --set auth.username=asya \
  --set auth.password=<secure-password>
```

## Step 2: Deploy API Gateway

Create a values file for the API gateway:

```yaml
# gateway-api-values.yaml
mode: api

config:
  postgresHost: asya-gateway-postgresql.asya-system.svc.cluster.local
  postgresDatabase: asya_gateway
  postgresUsername: asya
  postgresPassword: <secure-password>

ingress:
  enabled: true
  className: nginx
  hosts:
  - host: asya-api.example.com
    paths:
    - path: /
      pathType: Prefix

# Configure A2A auth (choose one)
a2a:
  apiKey: ""  # Set to enable API key auth
  jwt:
    jwksUrl: ""  # Set to enable JWT auth
    issuer: ""
    audience: ""

# Configure MCP auth (choose one)
mcp:
  apiKey: ""  # Set for simple Bearer token auth
  oauth:
    enabled: false  # Set to true for full OAuth 2.1
    issuer: ""
    secret: ""
    registrationToken: ""  # Set to protect /oauth/register
```

Deploy:

```bash
helm install asya-gateway deploy/helm-charts/asya-gateway/ \
  --namespace asya-system \
  -f gateway-api-values.yaml \
  --wait
```

## Step 3: Deploy Mesh Gateway

Create a values file for the mesh gateway:

```yaml
# gateway-mesh-values.yaml
mode: mesh

config:
  postgresHost: asya-gateway-postgresql.asya-system.svc.cluster.local
  postgresDatabase: asya_gateway
  postgresUsername: asya
  postgresPassword: <secure-password>

service:
  type: ClusterIP  # No Ingress for mesh
  port: 8080
```

Deploy:

```bash
helm install asya-gateway-mesh deploy/helm-charts/asya-gateway/ \
  --namespace asya-system \
  -f gateway-mesh-values.yaml \
  --wait
```

## Authentication Configuration

### A2A Authentication

Two schemes are supported with OR semantics — a request is authenticated if either check passes.

#### API Key

```yaml
a2a:
  apiKey: "your-secure-api-key"
```

Clients send:
```
X-API-Key: your-secure-api-key
```

#### JWT Bearer

```yaml
a2a:
  jwt:
    jwksUrl: "https://auth.example.com/.well-known/jwks.json"
    issuer: "https://auth.example.com"
    audience: "asya-api"
```

Clients send:
```
Authorization: Bearer <JWT>
```

The gateway validates signature, issuer, and audience claims.

#### Auth Disabled

When neither `apiKey` nor `jwt.jwksUrl` is set, A2A auth is disabled (all requests pass). This is the default for local development.

### MCP Authentication

Two modes are mutually exclusive.

#### Simple API Key

```yaml
mcp:
  apiKey: "your-mcp-api-key"
```

Clients send:
```
Authorization: Bearer your-mcp-api-key
```

Suitable for internal tooling (`asya-lab` CLI, known MCP hosts) where full OAuth is not needed.

#### OAuth 2.1 (Full MCP Spec Compliance)

```yaml
mcp:
  oauth:
    enabled: true
    issuer: "https://asya-api.example.com"
    secret: "a-32-byte-secret-for-hmac-signing"
    tokenTTL: 3600
    registrationToken: "registration-token"  # Protect /oauth/register
```

The gateway acts as its own authorization server, issuing HMAC-SHA256 JWTs.

**Dynamic Client Registration**:

`/oauth/register` is public by default. To restrict it, set `registrationToken` — callers must supply `Authorization: Bearer <registration-token>` to register.

**PKCE required**: All clients must use `code_challenge_method=S256`.

**Scopes** (issued but not yet enforced per-endpoint):

| Scope | Intended permission |
|-------|-------------------|
| `mcp:invoke` | Call tools, send messages |
| `mcp:read` | List tools, read task state |

## Flow Registration

A flow is exposed to the gateway as an **A2A agent** and/or an **MCP tool**. Each protocol
has its own registry ConfigMap, hot-reloaded without a pod restart (polled every 10s,
configurable via `ASYA_CONFIG_POLL_INTERVAL`; or force a reload — see below):

| Protocol | ConfigMap | Data key | Adapter mount |
|---|---|---|---|
| A2A | `asya-gateway-a2a-agents` | `agents.yaml` (`agents:` list) | `ASYA_A2A_CONFIG_DIR` |
| MCP | `asya-gateway-mcp-tools` | `tools.yaml` (`tools:` list) | `ASYA_MCP_CONFIG_DIR` |

Seed entries at deploy time via the chart's `a2aAgents` / `mcpTools` values; add or update them
later with the CLI (below) or by editing the ConfigMap directly. Each entry's `actor` field is
the flow's entrypoint actor (`start-<flow>` for compiled flows).

### Using the CLI (recommended)

The `asya expose` and `asya k apply` commands handle flow registration automatically:

```bash
# Compile the flow
asya compile text-flow -f src/flows/text_flow.py

# Create the gateway config (writes to common/ or overlay)
asya expose text-flow -d "Analyze text" --mcp --a2a --context dev

# Deploy actors + gateway config, auto-register with gateway
asya k apply text-flow --context dev
```

`asya expose` (or `asya patch --gateway`) writes a local `flow-expose.yaml` intent; `asya k apply`
upserts it (keyed by `name`) into the `asya-gateway-a2a-agents` / `asya-gateway-mcp-tools` ConfigMaps,
which the gateway hot-reloads. No deployment patch and no Helm upgrade needed.

To disable for an environment:

```bash
asya unexpose text-flow --context dev
asya k apply text-flow --context dev
```

### Using Helm Values

Seed agents/tools at deploy time via the chart's `a2aAgents` and `mcpTools` values:

```yaml
# values.yaml
a2aAgents:
- name: echo
  description: Echo back the input with a greeting
  actor: echo-actor          # the flow entrypoint actor
  timeout: 60
  streaming: true
  skills:
  - {id: echo, name: echo, description: Echo handler}
  inputModes: [text/plain, application/json]
  outputModes: [text/plain, application/json]

mcpTools:
- name: echo
  description: Echo back the input with a greeting
  actor: echo-actor
  timeout: 60
  inputSchema:
    type: object
    properties:
      name: {type: string, description: Name to greet}
    required: [name]
```

### Entry Fields

**A2A agent** (`agents.yaml`):

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Unique agent name; the A2A endpoint is `/a2a/<name>` |
| `actor` | yes | Flow entrypoint actor (`start-<flow>` for compiled flows) |
| `description` | yes | Surfaced in the agent card |
| `timeout` | no | Max seconds to wait for completion |
| `streaming` | no | Advertise SSE streaming support |
| `skills` | no | A2A skills `[{id, name, description, tags?, examples?}]` |
| `inputModes` / `outputModes` | no | MIME types (default `[text/plain, application/json]`) |

**MCP tool** (`tools.yaml`): same `name` / `actor` / `description` / `timeout`, plus
`inputSchema` (JSON Schema) and `progress` (bool — emit progress notifications).

### Manual ConfigMap edit

For custom setups, edit the registry ConfigMaps directly (the gateway hot-reloads):

```bash
kubectl edit configmap asya-gateway-a2a-agents   # data.agents.yaml -> agents: [...]
kubectl edit configmap asya-gateway-mcp-tools    # data.tools.yaml  -> tools:  [...]
```

### Verify Registration

```bash
# List available tools via MCP
curl -X POST http://asya-api.example.com/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Verify A2A skills
curl http://asya-api.example.com/.well-known/agent.json | jq '.skills'
```

### Force Immediate Reload

```bash
curl -X POST http://asya-gateway-mesh.asya-system.svc.cluster.local:8080/mesh/config-reload
```

## Environment Variable Reference

All auth-related env vars:

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

## Mesh Security

Mesh routes carry no authentication code. Security is enforced at the network layer:

- `asya-gateway-mesh` K8s Service is `ClusterIP` — no Ingress, no NodePort. It is physically unreachable from outside the cluster.
- Sidecars and crew actors reach it via in-cluster DNS: `asya-gateway-mesh.<namespace>.svc.cluster.local`.

For defense in depth, add a K8s NetworkPolicy restricting ingress to actor pods:

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

Alternatively, enable a service mesh (Istio/Linkerd) for automatic mTLS between all pods with zero Asya code changes.

## Troubleshooting

### Gateway pod fails to start

Check logs:
```bash
kubectl logs -n asya-system deployment/asya-gateway
kubectl logs -n asya-system deployment/asya-gateway-mesh
```

### Database connection fails

Verify PostgreSQL connectivity:
```bash
kubectl run psql-test --rm -i --restart=Never --image=postgres:15 \
  --namespace asya-system \
  --env="PGPASSWORD=<password>" \
  --command -- psql -h asya-gateway-postgresql.asya-system.svc.cluster.local -U asya -d asya_gateway -c "SELECT 1"
```

### Tools not appearing after ConfigMap update

Wait for the poll interval (default 10 seconds), or force reload:
```bash
curl -X POST http://asya-gateway-mesh.asya-system.svc.cluster.local:8080/mesh/config-reload
```

Check gateway logs:
```bash
kubectl logs -n asya-system deployment/asya-gateway -f
```

## Next Steps

- [Gateway Architecture](../reference/components/core-gateway.md)
- [Deploy actors](../usage/start-first-actor.md)
