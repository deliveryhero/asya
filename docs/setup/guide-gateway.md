# Setup Guide: Gateway Configuration

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

## Tool Registration

The gateway reads tool definitions from a ConfigMap named `gateway-flows`, mounted into the api pod. The gateway polls this ConfigMap every 10 seconds (configurable via `ASYA_CONFIG_POLL_INTERVAL`) and hot-reloads without a pod restart.

### Step 1: Create flows.yaml

```yaml
flows:
- name: echo
  entrypoint: echo-actor
  description: Echo back the input with a greeting
  mcp:
    inputSchema:
      type: object
      properties:
        name:
          type: string
          description: Name to greet
      required: [name]
```

### Multi-Actor Pipeline

```yaml
flows:
- name: text-analysis
  entrypoint: preprocess
  route_next: [inference, postprocess]
  description: Analyze text through a preprocessing, inference, and postprocessing pipeline
  timeout: 120
  mcp:
    inputSchema:
      type: object
      properties:
        text:
          type: string
          description: Text to analyze
      required: [text]
```

### Expose as Both MCP and A2A

```yaml
flows:
- name: text-analysis
  entrypoint: preprocess
  route_next: [inference, postprocess]
  description: Analyze text
  mcp:
    inputSchema:
      type: object
      properties:
        text:
          type: string
      required: [text]
  a2a: {}
```

### Flow Configuration Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Unique flow name; becomes the MCP tool name and A2A skill name |
| `entrypoint` | yes | First actor in the pipeline (actor name, not queue name) |
| `route_next` | no | Ordered list of subsequent actors |
| `description` | no | Human-readable description surfaced in tool/skill listings |
| `timeout` | no | Max seconds to wait for completion |
| `mcp` | no | Present = exposed as MCP tool; requires `inputSchema` |
| `a2a` | no | Present = exposed as A2A skill |

### Step 2: Apply the ConfigMap

```bash
kubectl create configmap gateway-flows \
  -n asya-system \
  --from-file=flows.yaml=flows.yaml \
  --dry-run=client -o yaml | kubectl apply -f -
```

Or patch the existing ConfigMap:

```bash
kubectl patch configmap gateway-flows -n asya-system \
  --type merge \
  -p "$(cat <<'EOF'
data:
  flows.yaml: |
    flows:
    - name: echo
      entrypoint: echo-actor
      description: Echo handler
      mcp:
        inputSchema:
          type: object
          properties:
            name:
              type: string
          required: [name]
EOF
)"
```

### Step 3: Verify Registration

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

- [Register tools in the gateway](../howto/register-gateway-tools.md)
- [Gateway Architecture](../architecture/asya-gateway.md)
- [Deploy actors](../howto/add-new-actor.md)
