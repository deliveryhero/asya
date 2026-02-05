# Asya Stagedoor Design Document

**Status:** Draft
**Date:** 2026-02-05
**Authors:** Design session with AI assistant

---

## 1. Overview

### 1.1 Problem Statement

Asya must serve two distinct user needs:

1. **Data Science Agility:** Instant, imperative deployment of AI actors via CLI/UI for rapid iteration in experimentation namespaces.
2. **Production Stability:** Declarative, reproducible deployments managed by GitOps controllers (FluxCD/ArgoCD) in production namespaces.

A strict "GitOps-only" approach introduces unacceptable latency for experimentation. Conversely, an "Imperative-only" approach creates ungoverned infrastructure without audit trails. We need a unified architecture that supports imperative experimentation while providing a frictionless path to declarative production.

### 1.2 Solution Summary

Introduce **asya-stagedoor** — a management plane service that:

- Provides a **React SPA** for visual flow editing and actor management
- Exposes an **MCP-compliant HTTP API** for CLI and AI agent integration
- Acts as a **facade over Kubernetes API** with scoped permissions (lab namespaces: read-write, prod namespaces: read-only)
- Enables **imperative-to-GitOps promotion** via export functionality

### 1.3 Key Principles

| Principle | Description |
|-----------|-------------|
| **Stateless** | Stagedoor maintains no persistent state; Kubernetes is the source of truth |
| **MCP-First** | API designed for AI agent consumption, humans use same API via UI/CLI |
| **Namespace Isolation** | Clear separation between experimentation (lab) and production namespaces |
| **GitOps-Compatible** | Exports generate clean manifests ready for git commit |
| **Profile-Driven** | Complexity hidden behind Crossplane Compositions ("flavors") |

### 1.4 Key Terminology

| Term | Definition |
|------|------------|
| **Profile** (aka Flavor) | A Crossplane Composition that defines a reusable actor configuration template. Profiles encapsulate scaling config, resource limits, node affinities, and defaults. DS selects by name (e.g., `profile: llm-heavy`); Crossplane expands to full spec. |
| **Lab Namespace** | Experimentation namespace (e.g., `lab-alice`) where DS can imperatively create/modify actors. Not managed by GitOps. |
| **Prod Namespace** | Production namespace managed by GitOps (Flux/ArgoCD). Stagedoor has read-only access. |
| **Flow** | A set of actors that process messages in sequence/parallel, identified by shared label `asya.sh/flow: <name>`. |
| **Claim** | A Crossplane XRD instance that users create. Crossplane expands claims into full K8s resources. |
| **Export** | The process of generating sanitized, GitOps-ready manifests from deployed or compiled actors. |

**Example Profiles:**

| Profile | Use Case | Key Settings |
|---------|----------|--------------|
| `fast-router` | Quick routing decisions (5ms) | minReplicas: 2, cooldown: 30s, 100m CPU |
| `llm-heavy` | LLM inference (30s+) | minReplicas: 1, cooldown: 600s, 8 CPU, 32Gi RAM, GPU |
| `batch-processing` | High-volume batch jobs | minReplicas: 0, maxReplicas: 100, scale-to-zero |
| `gpu-inference` | GPU-accelerated models | GPU request, node affinity for GPU nodes |

---

## 2. Goals and Non-Goals

### 2.1 Goals

- **G1:** Enable DS to visually create, edit, and deploy actor flows without writing YAML
- **G2:** Provide MCP-compliant API for AI coding agents to build and test actors
- **G3:** Support imperative deployment to lab namespaces with instant feedback
- **G4:** Generate GitOps-ready manifests via export for production promotion
- **G5:** Integrate with existing Asya components (gateway, operator, Crossplane)
- **G6:** Enforce security boundaries between lab and production namespaces

### 2.2 Non-Goals

- **NG1:** Replace GitOps controllers (Flux/ArgoCD) — stagedoor delegates sync to them
- **NG2:** Manage secrets — users configure secrets separately, stagedoor encourages best practices
- **NG3:** Build container images — out of scope, separate research (see `asya-0a`)
- **NG4:** Provide observability dashboards — delegate to SigNoz/Grafana
- **NG5:** Git integration (commit/push) — stagedoor exports files, user commits manually

---

## 3. Architecture

### 3.1 System Context

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLUSTER                                        │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     asya-stagedoor                                   │   │
│  │  ┌──────────────┐   ┌──────────────┐   ┌─────────────────────────┐  │   │
│  │  │ React SPA    │   │ HTTP API     │   │ Compiler Service        │  │   │
│  │  │ (static)     │──▶│ (MCP-compat) │──▶│ (asya flow compile + export) │  │   │
│  │  └──────────────┘   └──────────────┘   └─────────────────────────┘  │   │
│  │                            │                                         │   │
│  │                            ▼                                         │   │
│  │                     ┌──────────────┐                                 │   │
│  │                     │ K8s Client   │                                 │   │
│  │                     │ (scoped RBAC)│                                 │   │
│  │                     └──────────────┘                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                │                                            │
│         ┌──────────────────────┼──────────────────────┐                    │
│         ▼                      ▼                      ▼                    │
│  ┌─────────────┐       ┌─────────────┐       ┌─────────────────┐          │
│  │ lab-*       │       │ staging     │       │ prod            │          │
│  │ namespaces  │       │ namespace   │       │ namespace       │          │
│  │ (read-write)│       │ (read-only) │       │ (read-only)     │          │
│  └─────────────┘       └─────────────┘       └─────────────────┘          │
│         │                      │                      │                    │
│         ▼                      ▼                      ▼                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     Crossplane + asya-operator                       │   │
│  │  (Compositions expand claims → AsyncActors → Deployments + KEDA)    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     asya-gateway                                     │   │
│  │  (Business logic: HTTP → envelopes → queues, progress tracking)     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     Observability Stack                              │   │
│  │  (SigNoz/Loki for logs, traces; Grafana for dashboards)             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
          ▲                    ▲                    ▲
          │                    │                    │
      ┌───┴───┐            ┌───┴───┐            ┌───┴───┐
      │  DS   │            │  CLI  │            │  AI   │
      │(browser)           │(asya) │            │(MCP)  │
      └───────┘            └───────┘            └───────┘
```

### 3.2 Component Responsibilities

| Component | Responsibility | Technology |
|-----------|---------------|------------|
| **asya-stagedoor** | Management plane: CRUD actors, compile flows, export manifests | Go + React |
| **asya-gateway** | Business logic: HTTP ingress, envelope routing, progress tracking | Go |
| **asya-operator** | Reconcile AsyncActor CRDs → Deployments + sidecars | Go (Kubebuilder) |
| **Crossplane** | Expand profile claims → full AsyncActor specs | Crossplane Compositions |
| **Flux/ArgoCD** | Sync git manifests → cluster state | Standard GitOps |
| **SigNoz** | Logs, traces, metrics aggregation | ClickHouse-backed |

### 3.3 Gateway vs Stagedoor Distinction

| Aspect | asya-gateway | asya-stagedoor |
|--------|--------------|----------------|
| **Purpose** | Runtime business logic | Management plane |
| **Users** | Applications, actors, end-users | DS, platform engineers, AI agents |
| **Protocol** | A2A (future), HTTP/SSE | MCP-compliant HTTP |
| **Operations** | Send messages, track envelopes | CRUD actors, compile flows, export |
| **Load pattern** | High throughput, latency-sensitive | Low throughput, interactive |
| **Security** | API keys, rate limiting | OIDC/OAuth, namespace RBAC |

### 3.4 Namespace Model

```
┌────────────────────────────────────────────────────────────────┐
│                    Namespace Topology                          │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  lab-alice/        ← DS "alice" experiments here               │
│  lab-bob/          ← DS "bob" experiments here                 │
│  lab-agents/       ← AI agents create ephemeral actors here    │
│                                                                │
│  staging/          ← GitOps-managed, read-only via stagedoor   │
│  prod/             ← GitOps-managed, read-only via stagedoor   │
│                                                                │
│  asya-system/      ← Operator, gateway, stagedoor live here    │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Stagedoor permissions:**
- `lab-*` namespaces: full CRUD (create, read, update, delete actors)
- `staging`, `prod`: read-only (list, get, logs)
- Other namespaces: no access

---

## 4. UX Flows

### 4.1 Flow Development Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DS WORKFLOW                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. AUTHOR                                                                  │
│     └─ DS writes flow.py locally (Python DSL)                              │
│                                                                             │
│  2. VISUALIZE                                                               │
│     ├─ DS opens stagedoor UI in browser (or VSCode Extension integration)  │
│     ├─ Uploads flow.py (or pastes code)                                    │
│     ├─ Stagedoor compiles server-side → renders React Flow graph           │
│     └─ DS sees actors, connections, conditional branches                   │
│                                                                             │
│  3. CONFIGURE                                                               │
│     ├─ DS clicks on actors in graph                                        │
│     ├─ Sets: name, profile (flavor), env vars, labels                      │
│     ├─ UI validates the availability of selected profiles                  │
│     └─ Changes reflected in graph (re-render on edit)                      │
│                                                                             │
│  4. (Optional) TEST LOCALLY                                                 │
│     ├─ DS runs: asya local up flows/my-flow/                               │
│     ├─ Tool generates docker-compose.yml from compiled manifests           │
│     ├─ Spins up: RabbitMQ + actor containers (no K8s required)             │
│     ├─ DS tests flow logic locally before deploying to cluster             │
│     └─ Note: Profiles/KEDA don't apply locally (uses defaults)             │
│     └─ Future: see bead asya-u8x for implementation                        │
│                                                                             │
│  5. DEPLOY TO LAB                                                           │
│     ├─ DS clicks "Deploy to lab-alice"                                     │
│     ├─ Stagedoor creates Crossplane claims via K8s API                     │
│     ├─ Crossplane expands → AsyncActors → Deployments                      │
│     └─ UI shows deployment status (pending → running)                      │
│                                                                             │
│  6. TEST IN CLUSTER                                                         │
│     ├─ DS clicks "Send Test" in stagedoor UI (or uses asya-cli)            │
│     ├─ Enters test payload JSON + gateway URL                              │
│     ├─ UI calls asya-gateway directly (like asya mcp call)                 │
│     ├─ UI displays real-time envelope progress (gateway SSE stream)        │
│     ├─ DS views actor logs via stagedoor (SigNoz/Loki integration)         │
│     ├─ On completion: UI shows final result or error details               │
│     └─ Iterates: modify flow.py (maybe right in UI) → re-upload → re-deploy│
│                                                                             │
│  7. EXPORT                                                                  │
│     ├─ DS clicks "Export" in UI                                            │
│     ├─ Stagedoor generates:                                                │
│     │   ├─ manifests/*.yaml (Crossplane claims, sanitized)                 │
│     │   ├─ routers.py (generated router handlers)                          │
│     │   ├─ flow.dot + flow.png (documentation)                             │
│     │   └─ kustomization.yaml (optional)                                   │
│     ├─ DS downloads as zip                                                 │
│     └─ DS extracts to repo: flows/<flow-name>/                             │
│                                                                             │
│  8. PROMOTE TO PROD                                                         │
│     ├─ DS commits: git add flows/<flow-name> && git commit && git push     │
│     ├─ Flux/ArgoCD detects change                                          │
│     ├─ GitOps syncs manifests to prod namespace                            │
│     └─ DS monitors via stagedoor (read-only) or Grafana                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 CLI-Equivalent Workflow

For power users or automation, the same workflow via `asya-cli`:

```bash
# 1. Author (local)
vim flows/my-flow/flow.py

# 2. Validate (local)
asya flow validate flows/my-flow/flow.py

# 3. Compile (local or via stagedoor)
asya flow compile flows/my-flow/flow.py --output-dir flows/my-flow/compiled/

# 4. Deploy to lab (via stagedoor API)
asya deploy flows/my-flow/compiled/ --namespace lab-alice

# 5. Test (via gateway)
asya mcp call my-flow-entrypoint '{"input": "test"}'
asya mcp stream <envelope-id>

# 6. View logs (via stagedoor)
asya logs my-actor --namespace lab-alice --follow

# 7. Export is already done (compile step generated manifests)
# Just commit and push
git add flows/my-flow/ && git commit -m "Add my-flow" && git push
```

### 4.3 AI Agent Workflow (MCP)

AI coding agents interact via MCP tools exposed by stagedoor:

```json
{
  "tools": [
    {
      "name": "list_actors",
      "description": "List actors in a namespace",
      "parameters": {"namespace": "string"}
    },
    {
      "name": "get_actor",
      "description": "Get actor details including status and recent logs",
      "parameters": {"namespace": "string", "name": "string"}
    },
    {
      "name": "compile_flow",
      "description": "Compile a flow.py and return the graph structure",
      "parameters": {"source_code": "string"}
    },
    {
      "name": "deploy_actor",
      "description": "Deploy an actor to a lab namespace",
      "parameters": {"namespace": "string", "manifest": "object"}
    },
    {
      "name": "delete_actor",
      "description": "Delete an actor from a lab namespace",
      "parameters": {"namespace": "string", "name": "string"}
    },
    {
      "name": "get_logs",
      "description": "Get recent logs for an actor",
      "parameters": {"namespace": "string", "name": "string", "lines": "integer"}
    },
    {
      "name": "list_profiles",
      "description": "List available actor profiles (flavors)",
      "parameters": {}
    }
  ]
}
```

### 4.4 Export Sanitization

The export process must sanitize manifests for GitOps compatibility:

| Field | Action |
|-------|--------|
| `metadata.uid` | Remove |
| `metadata.resourceVersion` | Remove |
| `metadata.creationTimestamp` | Remove |
| `metadata.managedFields` | Remove |
| `status` | Remove entirely |
| `metadata.annotations["kustomize.toolkit.fluxcd.io/prune"]` | Remove (was "disabled" during experiment) |
| Secret references | Preserve `secretRef`, redact inline values with TODO comment |
| `metadata.namespace` | Preserve (explicit is safer for GitOps) |
| `spec.profile` | Preserve (Crossplane resolves server-side) |

---

## 5. API Surface

### 5.1 HTTP Endpoints

Stagedoor exposes a REST API (MCP-compatible via JSON-RPC wrapper):

**Actor Management:**
```
GET    /api/v1/namespaces/{ns}/actors          # List actors
GET    /api/v1/namespaces/{ns}/actors/{name}   # Get actor details
POST   /api/v1/namespaces/{ns}/actors          # Create actor (lab only)
PUT    /api/v1/namespaces/{ns}/actors/{name}   # Update actor (lab only)
DELETE /api/v1/namespaces/{ns}/actors/{name}   # Delete actor (lab only)
GET    /api/v1/namespaces/{ns}/actors/{name}/logs   # Get actor logs
```

**Flow Management:**
```
GET    /api/v1/namespaces/{ns}/flows           # List flows (by label)
GET    /api/v1/namespaces/{ns}/flows/{name}    # Get flow (aggregated actors)
DELETE /api/v1/namespaces/{ns}/flows/{name}    # Delete flow (all labeled actors, lab only)
```

**Compiler:**
```
POST   /api/v1/compile                         # Compile flow.py → graph + manifests
POST   /api/v1/export                          # Generate downloadable zip
```

**Profiles:**
```
GET    /api/v1/profiles                        # List available profiles
GET    /api/v1/profiles/{name}                 # Get profile details
```

**Note:** Testing (send messages, track envelopes) is done via **asya-gateway** directly, not through stagedoor. The stagedoor UI calls gateway's public API, same as asya-cli.

**MCP Endpoint:**
```
POST   /mcp                                    # MCP JSON-RPC 2.0 endpoint
```

### 5.2 MCP Tool Mapping

| MCP Tool | HTTP Equivalent |
|----------|-----------------|
| `list_actors` | `GET /api/v1/namespaces/{ns}/actors` |
| `get_actor` | `GET /api/v1/namespaces/{ns}/actors/{name}` |
| `deploy_actor` | `POST /api/v1/namespaces/{ns}/actors` |
| `delete_actor` | `DELETE /api/v1/namespaces/{ns}/actors/{name}` |
| `get_logs` | `GET /api/v1/namespaces/{ns}/actors/{name}/logs` |
| `compile_flow` | `POST /api/v1/compile` |
| `list_profiles` | `GET /api/v1/profiles` |

**Note:** Message sending and envelope tracking tools are exposed by **asya-gateway**, not stagedoor. AI agents use gateway's MCP endpoint for runtime operations.

---

## 6. Security Model

### 6.1 Authentication

Stagedoor supports multiple authentication methods:

| Method | Use Case | Implementation |
|--------|----------|----------------|
| **OIDC/OAuth2** | Browser UI, human users | Integrate with corporate IdP (Okta, Google, etc.) |
| **API Keys** | CLI, automation | Stored in K8s Secret, validated per-request |
| **ServiceAccount** | In-cluster agents | K8s token, automatic via pod identity |

### 6.2 Authorization (Namespace RBAC)

Stagedoor enforces namespace-level permissions:

```yaml
# Example: ClusterRole for DS user
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: asya-ds-role
rules:
  # Lab namespaces: full access
  - apiGroups: ["asya.sh"]
    resources: ["asyncactors"]
    verbs: ["get", "list", "create", "update", "delete"]
  # Prod namespaces: read-only
  - apiGroups: ["asya.sh"]
    resources: ["asyncactors"]
    verbs: ["get", "list"]
---
# Bind to specific namespaces via RoleBindings
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: alice-lab-access
  namespace: lab-alice
subjects:
  - kind: User
    name: alice@company.com
roleRef:
  kind: ClusterRole
  name: asya-ds-role
```

### 6.3 Namespace Classification

Stagedoor configuration defines namespace access levels:

```yaml
# stagedoor config
namespaces:
  lab:
    pattern: "lab-*"
    access: read-write
    allowCreate: true
    allowDelete: true
  staging:
    pattern: "staging"
    access: read-only
  production:
    pattern: "prod"
    access: read-only
  agents:
    pattern: "lab-agents"
    access: read-write
    allowCreate: true
    allowDelete: true
    # Future: restrict to specific ServiceAccounts
```

### 6.4 Security Boundaries

| Boundary | Enforcement |
|----------|-------------|
| **Namespace isolation** | Stagedoor validates namespace pattern before K8s API call |
| **Lab vs Prod** | Write operations rejected for non-lab namespaces (allowed namespaces to be whitelisted) |
| **Secret exposure** | Export sanitizes secrets, adds TODO comments |
| **Audit logging** | All mutations logged with user identity and timestamp. Logs sinked to standard logging solution (e.g. Loki) |
| **Rate limiting** | Per-user limits to prevent abuse |

Important: asya-stagedoor is stateless, its configuration is stored in its environment variables or ConfigMap objects.


### 6.5 Stagedoor ServiceAccount

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: asya-stagedoor
  namespace: asya-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: asya-stagedoor-role
rules:
  # Read Crossplane claims (all namespaces)
  - apiGroups: ["asya.sh"]
    resources: ["asyncactors"]
    verbs: ["get", "list", "watch"]
  # Write only to lab-* namespaces (enforced by stagedoor logic + admission webhook)
  - apiGroups: ["asya.sh"]
    resources: ["asyncactors"]
    verbs: ["create", "update", "delete"]
  # Read pods/logs for actor debugging
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list"]
  # Read Crossplane Compositions (profiles)
  - apiGroups: ["apiextensions.crossplane.io"]
    resources: ["compositions"]
    verbs: ["get", "list"]
```

---

## 7. Integration with Existing Components

### 7.1 Crossplane Integration

Stagedoor works with Crossplane Compositions to provide the "profile" abstraction:

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  User creates   │         │  Crossplane     │         │  asya-operator  │
│  AsyncActor     │────────▶│  expands claim  │────────▶│  creates pods   │
│  claim          │         │  via Composition│         │  + sidecars     │
│  (profile: X)   │         │  (profile X)    │         │                 │
└─────────────────┘         └─────────────────┘         └─────────────────┘
```

**Profile = Composition:**
- Platform engineers define Crossplane Compositions (e.g., `llm-heavy`, `fast-router`)
- Each Composition specifies: scaling config, resource limits, node affinities, etc.
- Users select profile by name; Crossplane expands to full spec
- Exported YAMLs remain simple (just `profile: llm-heavy`)

### 7.2 Gateway Integration

Stagedoor and Gateway are **separate public-facing services** with distinct purposes:

| Service | Statefulness | Purpose | Users |
|---------|--------------|---------|-------|
| **asya-gateway** | Stateful (PostgreSQL) | Business logic: send messages, track envelopes | Apps, actors, DS, AI agents |
| **asya-stagedoor** | Stateless | Very limited management plane: CRUD for actors, compile flows, provide React-based SPA for rendering flows and editing actors, streaming logs and testing actors (by making calls to asya-gateway) | DS, platform engineers, AI agents |

**Testing Flow (UI calls Gateway directly):**

```
┌─────────────────┐                              ┌─────────────────┐
│ Stagedoor UI    │                              │  asya-gateway   │
│ (browser)       │──── direct HTTP call ───────▶│  (public API)   │
│ "Send Test"     │                              │  /tools/call    │
└─────────────────┘                              └─────────────────┘
        │                                                │
        │ (configure gateway URL)                        ▼
        │                                        ┌─────────────────┐
        └─ Same as asya-cli:                     │  Actor Queue    │
           asya mcp call <tool> <payload>        └─────────────────┘
```

**How it works:**
- Stagedoor UI has a "Gateway URL" configuration field (like asya-cli's `--url` flag)
- "Send Test" button opens a modal where DS enters payload JSON
- UI makes direct HTTP call to gateway (browser → gateway, not through stagedoor backend)
- UI displays envelope ID and streams progress via gateway's SSE endpoint
- Functionally identical to `asya mcp call` / `asya mcp stream`

| Use Case | Component | How |
|----------|-----------|-----|
| Send test message | Gateway (direct) | UI calls gateway `/tools/call` directly |
| Track envelope progress | Gateway (direct) | UI subscribes to gateway SSE stream |
| View actor logs | Stagedoor | Query SigNoz/Loki, filter by actor labels |
| Deploy new actor | Stagedoor | Create Crossplane claim via K8s API |

### 7.3 GitOps Integration

Stagedoor is designed to complement, not replace, GitOps:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GitOps Flow                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Experiment (Stagedoor)              Production (GitOps)            │
│  ─────────────────────               ──────────────────             │
│                                                                     │
│  1. DS deploys to lab-alice    ──▶   (not tracked in git)          │
│  2. DS iterates, tests         ──▶   (ephemeral)                   │
│  3. DS exports manifests       ──▶   flows/my-flow/*.yaml          │
│  4. DS commits to git          ──▶   git push                      │
│  5. (stagedoor not involved)   ──▶   Flux/ArgoCD syncs to prod     │
│  6. DS monitors via stagedoor  ──▶   (read-only view)              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Supported GitOps tools:**
- **Flux** (recommended): Lightweight, modular, no UI dependency
- **ArgoCD**: Richer UI, heavier installation

### 7.4 Observability Integration

Stagedoor proxies logs from the observability stack:

```
┌─────────────┐       ┌─────────────┐       ┌─────────────┐
│  Stagedoor  │──────▶│  SigNoz     │◀──────│  Actor Pods │
│  /logs API  │       │  (query)    │       │  (stdout)   │
└─────────────┘       └─────────────┘       └─────────────┘
```

**Log query filters:**
- `namespace`: Target namespace
- `app.kubernetes.io/name`: Actor name
- `asya.sh/flow`: Flow name (for flow-level logs)
- `trace_id`: Distributed trace correlation

---

## 8. Technology Choices

### 8.1 Backend: Go

**Rationale:**
- Consistent with asya-gateway and asya-operator
- Excellent K8s client libraries (client-go)
- Efficient for HTTP API serving
- Can embed Python runtime for flow compilation (or shell out to `asya flow compile`)

### 8.2 Frontend: React + React Flow

**Rationale:**
- React Flow for DAG visualization (purpose-built for flow graphs)
- React ecosystem for UI components
- TypeScript for type safety
- Bundled as static files, served by Go backend

### 8.3 Flow Compilation

**Options:**
1. **Shell out to asya-cli**: Stagedoor calls `asya flow compile` as subprocess
2. **Embed Python runtime**: Use embedded Python (e.g., go-python)
3. **Port to Go**: Rewrite flow compiler in Go

**Recommendation:** Option 1 (shell out) for simplicity. Python is already required for asya-runtime.

---

## 9. Open Questions and Future Work

### 9.1 Open Questions

| Question | Status | Notes |
|----------|--------|-------|
| How are flows identified? | Research: `asya-5av` | Label-based (`asya.sh/flow: name`) |
| How are images built? | Research: `asya-0a` | ConfigMap injection vs CI builds |
| Cross-namespace routing? | Research: `asya-1k0` | `namespace/actor-name` convention |
| Secret management tooling? | Research: `asya-n93` | Encourage best practices via docs/tooling |

### 9.2 Future Enhancements

| Enhancement | Priority | Description |
|-------------|----------|-------------|
| **Embedded log viewer** | P2 | Embed SigNoz panels in stagedoor UI |
| **Flow diff view** | P3 | Compare deployed vs local flow versions |
| **Collaborative editing** | P4 | Multiple DS editing same flow (WebSocket sync) |
| **Template library** | P3 | Pre-built flow templates (RAG, batch inference, etc.) |
| **Cost estimation** | P4 | Estimate resource costs before deployment |
| **Agentic actor spawning** | P4 | AI agents creating ephemeral actors dynamically |

### 9.3 Implementation Phases

| Phase | Scope | Deliverables |
|-------|-------|--------------|
| **Phase 1: MVP** | Core API | HTTP API for CRUD, compile, export. CLI integration. |
| **Phase 2: UI** | React SPA | Flow visualization, interactive editing, deploy button. |
| **Phase 3: MCP** | AI integration | MCP-compliant endpoint, tool definitions. |
| **Phase 4: Observability** | Logs integration | Log proxy, trace correlation, embedded panels. |

---

## 10. References

- RFC: Dual-Mode Deployment Strategy (`docs/rfc/thoughts-gitops-dev-flow.md`)
- Crossplane Compositions documentation
- MCP Protocol specification
- React Flow documentation
- SigNoz API documentation

---

## Appendix A: Related Beads

| Bead ID | Title | Priority |
|---------|-------|----------|
| `asya-n93` | Secret management tooling | - |
| `asya-5av` | Flow as labeled actors research | - |
| `asya-0a` | Image build workflow | - |
| `asya-1k0` | Cross-namespace routing design | P4 |
| `asya-u8x` | Implement asya local: docker-compose from XRDs | P4 |
