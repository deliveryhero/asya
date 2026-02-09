# Asya Management Plane Design Document

**Status:** Draft (revised)
**Date:** 2026-02-05
**Updated:** 2026-02-06
**Authors:** Design session with AI assistant

**Supersedes:** Original asya-stagedoor in-cluster service design.
**Related:** [ADR: AsyncFlow CRD vs Labels](../rfc/adr-async-flow-crd-vs-labels.md), [RFC: Dual-Mode Deployment](../rfc/thoughts-gitops-dev-flow.md), [RFC: Crossplane Architecture](../rfc/rfc-crossplane.md)

---

## 1. Overview

### 1.1 Problem Statement

Asya must serve two distinct user needs:

1. **Data Science Agility:** Instant, imperative deployment of AI actors via CLI for rapid iteration in experimentation namespaces.
2. **Production Stability:** Declarative, reproducible deployments managed by GitOps controllers (FluxCD/ArgoCD) in production namespaces.

A strict "GitOps-only" approach introduces unacceptable latency for experimentation. Conversely, an "Imperative-only" approach creates ungoverned infrastructure without audit trails. We need a unified architecture that supports imperative experimentation while providing a frictionless path to declarative production.

### 1.2 Solution Summary

Replace the originally proposed **asya-stagedoor** in-cluster service with **local tooling**:

- **asya-cli** — primary management interface. Wraps `kubectl` for actor/flow CRUD, compiles flows locally, generates manifests for GitOps.
- **VSCode extension** — flow visualization (renders `.dot`/`.png` from compiler), actor status panels, integrated terminal for asya-cli.
- **Local MCP server** — thin wrapper over asya-cli commands, enables AI coding agents (Cursor, Claude Code, etc.) to manage actors from the DS's development environment.
- **deployer crew actor** (future) — in-cluster actor with K8s API access for agentic actor spawning, when AI agents inside the cluster need to create new actors.

### 1.3 Why Not an In-Cluster Service

The original design proposed **asya-stagedoor** — a Go+React service deployed in the cluster that provides a web UI, REST API, and MCP endpoint for actor management. This was rejected because:

| Concern | In-cluster service (stagedoor) | Local tooling (CLI + VSCode) |
|---------|-------------------------------|------------------------------|
| **Infra maintenance** | Go backend, React SPA, Helm chart, TLS, ingress | Zero cluster footprint |
| **Security surface** | ServiceAccount with cluster-wide AsyncActor CRUD, OIDC auth, namespace RBAC enforcement | Standard kubeconfig + K8s RBAC (already exists) |
| **Auth complexity** | Custom OIDC/OAuth integration, API keys, session management | `kubelogin` / cloud provider auth (already configured) |
| **What it wraps** | K8s API — essentially `kubectl` behind a web UI | `kubectl` directly |
| **Where DS works** | Browser (separate from IDE) | VSCode / terminal (where DS already works) |
| **AI agent access** | In-cluster MCP endpoint | Local MCP server (same trust boundary as DS's kubeconfig) |

The key insight: **stagedoor is a facade over `kubectl` with a web UI**. The facade adds maintenance burden and security surface without adding capabilities that `kubectl` + RBAC don't already provide. Visualization (the one thing `kubectl` can't do) belongs in the IDE, not in a separate web service.

### 1.4 Key Principles

| Principle | Description |
|-----------|-------------|
| **Local-first** | All management tools run on the DS's machine; no in-cluster management service |
| **kubectl is the API** | Actor CRUD is `kubectl apply/delete` on AsyncActor claims; no custom REST API |
| **IDE-native** | Visualization and status in VSCode, where DS already works |
| **MCP for AI agents** | Local MCP server wraps asya-cli; AI coding agents use the same tools as humans |
| **Standard K8s security** | Kubeconfig + RBAC; no custom auth layer |
| **Namespace isolation** | Lab namespaces for experimentation, prod for GitOps (enforced by K8s RBAC) |
| **Flavor-driven** | Complexity hidden behind Crossplane Compositions ("flavors") |

### 1.5 Key Terminology

| Term | Definition |
|------|------------|
| **Flavor** | A Crossplane Composition that defines a reusable actor configuration template. Flavors encapsulate scaling config, resource limits, node affinities, and defaults. DS selects by name (e.g., `flavor: llm-heavy`); Crossplane expands to full spec. |
| **Lab Namespace** | Experimentation namespace (e.g., `lab-alice`) where DS can imperatively create/modify actors. Not managed by GitOps. |
| **Prod Namespace** | Production namespace managed by GitOps (Flux/ArgoCD). DS has read-only access via kubeconfig. |
| **Flow** | A set of actors that process messages in sequence/parallel, identified by shared label `asya.sh/flow: <name>`. See [ADR: AsyncFlow CRD vs Labels](../rfc/adr-async-flow-crd-vs-labels.md). |
| **Claim** | A Crossplane XRD instance that users create. Crossplane expands claims into full K8s resources. |

**Example Flavors:**

| Flavor | Use Case | Key Settings |
|---------|----------|--------------|
| `fast-router` | Quick routing decisions (5ms) | minReplicas: 2, cooldown: 30s, 100m CPU |
| `llm-heavy` | LLM inference (30s+) | minReplicas: 1, cooldown: 600s, 8 CPU, 32Gi RAM, GPU |
| `batch-processing` | High-volume batch jobs | minReplicas: 0, maxReplicas: 100, scale-to-zero |
| `gpu-inference` | GPU-accelerated models | GPU request, node affinity for GPU nodes |

---

## 2. Goals and Non-Goals

### 2.1 Goals

- **G1:** Enable DS to deploy and manage actor flows via CLI without writing YAML manually
- **G2:** Provide local MCP server for AI coding agents to build and test actors
- **G3:** Visualize flows in VSCode (graph rendering from compiler output)
- **G4:** Support imperative deployment to lab namespaces with instant feedback
- **G5:** Generate GitOps-ready manifests via `asya flow deploy --output-dir` for production promotion
- **G6:** Enforce security boundaries between lab and production via standard K8s RBAC
- **G7:** Enable in-cluster actor spawning via deployer crew actor (future)

### 2.2 Non-Goals

- **NG1:** Build an in-cluster web UI or management service
- **NG2:** Replace GitOps controllers (Flux/ArgoCD) — CLI generates manifests, GitOps applies them
- **NG3:** Manage secrets — users configure secrets separately via External Secrets, SealedSecrets, etc.
- **NG4:** Build container images — out of scope, separate research (see `asya-0a`)
- **NG5:** Provide observability dashboards — delegate to SigNoz/Grafana
- **NG6:** Implement custom authentication — use standard kubeconfig/OIDC

---

## 3. Architecture

### 3.1 System Context

```
DS Workstation                                    Kubernetes Cluster
──────────────                                    ──────────────────

┌─────────────────────────┐
│  VSCode                 │
│  ├─ Asya Extension      │          kubeconfig
│  │  (flow graph,        │       ┌─────────────┐
│  │   actor status)      │       │             │
│  ├─ Terminal             │       │  K8s API    │
│  │  └─ asya-cli ────────────────▶│  Server     │
│  └─ AI Agent (MCP)      │       │             │
│     └─ local MCP server ─────┐  └──────┬──────┘
│        (wraps asya-cli)  │   │         │
└─────────────────────────┘   │         │
                               │         ▼
                               │  ┌─────────────────────────────────────┐
                               │  │  Crossplane + asya-injector          │
                               │  │  (Compositions → Deployments + KEDA) │
                               │  └─────────────────────────────────────┘
                               │         │
                               │         ▼
                               │  ┌──────────────────┐  ┌──────────────┐
                               │  │  lab-alice/       │  │  prod/       │
                               │  │  (experiment)     │  │  (GitOps)    │
                               │  └──────────────────┘  └──────────────┘
                               │         │
                               │         ▼
                               │  ┌─────────────────────────────────────┐
                               └─▶│  asya-gateway                       │
                                  │  (runtime: messages, envelopes, SSE)│
                                  └─────────────────────────────────────┘
```

### 3.2 Component Responsibilities

| Component | Responsibility | Runs where |
|-----------|---------------|------------|
| **asya-cli** | Actor/flow CRUD, compile, deploy, export, expose | DS workstation |
| **VSCode extension** | Flow visualization, actor status, integrated terminal | DS workstation |
| **Local MCP server** | Expose asya-cli commands as MCP tools for AI agents | DS workstation |
| **asya-gateway** | Runtime: send messages, track envelopes, SSE streaming | In-cluster |
| **Crossplane** | Expand claims into AsyncActors, queues, KEDA, deployments | In-cluster |
| **asya-injector** | Sidecar injection via mutating webhook | In-cluster |
| **deployer crew actor** | In-cluster actor spawning (future, see Section 7) | In-cluster |
| **Flux/ArgoCD** | Sync git manifests to cluster state | In-cluster |

### 3.3 Gateway vs CLI Distinction

| Aspect | asya-gateway | asya-cli |
|--------|-------------|----------|
| **Purpose** | Runtime business logic | Management plane |
| **Runs where** | In-cluster | DS workstation |
| **Users** | Applications, actors, end-users | DS, platform engineers, AI agents |
| **Protocol** | A2A (future), HTTP/SSE | kubectl wrapper |
| **Operations** | Send messages, track envelopes | CRUD actors/flows, compile, deploy |
| **Load pattern** | High throughput, latency-sensitive | Low throughput, interactive |

### 3.4 Namespace Model

```
┌────────────────────────────────────────────────────────────────┐
│                    Namespace Topology                          │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  lab-alice/        <- DS "alice" experiments here               │
│  lab-bob/          <- DS "bob" experiments here                 │
│                                                                │
│  staging/          <- GitOps-managed, DS has read-only access   │
│  prod/             <- GitOps-managed, DS has read-only access   │
│                                                                │
│  asya-system/      <- Crossplane, gateway, injector live here   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**Permissions enforced by standard K8s RBAC** (no custom auth layer):

```yaml
# ClusterRole for DS user
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: asya-ds-role
rules:
  - apiGroups: ["asya.sh"]
    resources: ["asyncactors"]
    verbs: ["get", "list", "create", "update", "delete"]
---
# Lab namespace: full access
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
---
# Prod namespace: read-only
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: alice-prod-readonly
  namespace: prod
subjects:
  - kind: User
    name: alice@company.com
roleRef:
  kind: ClusterRole
  name: asya-ds-readonly  # verbs: [get, list] only
```

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
│  2. COMPILE                                                                 │
│     ├─ asya flow compile flow.py --output-dir compiled/ --plot             │
│     ├─ Generates: routers.py, flow.dot, flow.png                          │
│     └─ DS previews flow.png in VSCode (or VSCode extension renders .dot)  │
│                                                                             │
│  3. (Optional) TEST LOCALLY                                                 │
│     ├─ DS runs: asya local up compiled/                                    │
│     ├─ Tool generates docker-compose.yml from compiled manifests           │
│     ├─ Spins up: RabbitMQ + actor containers (no K8s required)             │
│     ├─ DS tests flow logic locally before deploying to cluster             │
│     └─ Note: Flavors/KEDA don't apply locally (uses defaults)              │
│                                                                             │
│  4. DEPLOY TO LAB                                                           │
│     ├─ asya flow deploy compiled/ --flow-name X -n lab-alice               │
│     ├─ CLI creates AsyncActor claims + ConfigMaps via kubectl              │
│     ├─ All resources labeled asya.sh/flow=X                                │
│     ├─ Crossplane expands claims -> queues, deployments, KEDA              │
│     └─ DS monitors: kubectl get asya -n lab-alice -w                       │
│                                                                             │
│  5. TEST IN CLUSTER                                                         │
│     ├─ asya mcp call <tool> '{"input": "test"}'                           │
│     ├─ asya mcp stream <envelope-id>                                       │
│     ├─ kubectl logs -n lab-alice -l asya.sh/flow=X --follow                │
│     └─ Iterates: modify flow.py -> recompile -> redeploy                   │
│                                                                             │
│  6. PROMOTE TO PROD                                                         │
│     ├─ asya flow deploy compiled/ --flow-name X --output-dir manifests/    │
│     ├─ CLI generates clean YAML files locally (like helm template)         │
│     ├─ DS commits: git add manifests/ && git commit && git push            │
│     ├─ Flux/ArgoCD detects change, syncs to prod namespace                 │
│     └─ DS monitors: kubectl get asya -n prod -l asya.sh/flow=X            │
│                                                                             │
│  7. EXPOSE AS MCP TOOL (optional)                                           │
│     ├─ asya expose X                                                       │
│     ├─ CLI auto-detects: tool name, description (docstring), parameters    │
│     ├─ Updates gateway-tools ConfigMap                                      │
│     └─ Gateway reloads via fsnotify                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 CLI Commands

```bash
# 1. Author (local)
vim flows/my-flow/flow.py

# 2. Compile (local, no cluster needed)
asya flow compile flows/my-flow/flow.py --output-dir compiled/ --plot

# 3. Deploy to lab (imperative, direct kubectl apply)
asya flow deploy compiled/ --flow-name my-flow -n lab-alice

# 4. Test (via gateway)
asya mcp call my-flow-entrypoint '{"input": "test"}'
asya mcp stream <envelope-id>

# 5. View logs
kubectl logs -n lab-alice -l asya.sh/flow=my-flow -f

# 6. Promote to prod (generate manifests for git)
asya flow deploy compiled/ --flow-name my-flow --output-dir manifests/
git add manifests/ && git commit -m "Add my-flow" && git push

# 7. Expose as MCP tool
asya expose my-flow

# 8. Undeploy
asya flow undeploy my-flow -n lab-alice
```

Note: CLI command surface to be designed carefully in a separate bead. Main design principles:
- Simplicity: `asya <verb> <args>`
- Contexts (like kubectl): same commands work across namespaces, local docker, local python

### 4.3 AI Coding Agent Workflow (Local MCP)

AI coding agents (Cursor, Claude Code, Windsurf, etc.) interact via a **local MCP server** that wraps asya-cli commands:

```
┌──────────────────┐        ┌──────────────────┐        ┌─────────────┐
│  AI Coding Agent │──MCP──▶│  Local MCP Server│──CLI──▶│  kubectl    │
│  (Cursor, etc.)  │        │  (asya-mcp)      │        │  (K8s API)  │
└──────────────────┘        └──────────────────┘        └─────────────┘
```

MCP tools exposed by the local server:

| MCP Tool | Implementation |
|----------|----------------|
| `list_actors` | `kubectl get asya -n <ns>` |
| `get_actor` | `kubectl get asya <name> -n <ns> -o yaml` |
| `deploy_actor` | `kubectl apply -f <manifest>` |
| `delete_actor` | `kubectl delete asya <name> -n <ns>` |
| `get_logs` | `kubectl logs -n <ns> -l asya.sh/actor=<name>` |
| `list_flows` | `kubectl get asya -n <ns> -l asya.sh/flow` with grouping |
| `compile_flow` | `asya flow compile <source>` (local, no cluster) |
| `deploy_flow` | `asya flow deploy <compiled> --flow-name <name>` |
| `delete_flow` | `asya flow undeploy <name> -n <ns>` |
| `list_flavors` | `kubectl get compositions -l asya.sh/flavor` |

**Runtime operations** (send messages, track envelopes) use **asya-gateway** MCP tools directly — the local MCP server doesn't duplicate these. The AI agent connects to both:
- Local MCP server for management (CRUD actors, compile flows)
- Gateway MCP endpoint for runtime (send messages, stream progress)

### 4.4 VSCode Extension

The VSCode extension provides visualization that `kubectl` cannot:

| Feature | Implementation |
|---------|----------------|
| **Flow graph** | Render `.dot` files from compiler output using Graphviz/d3 |
| **Actor status panel** | Poll `kubectl get asya -n <ns> -o json`, display as tree/table |
| **Flow status** | Group actors by `asya.sh/flow` label, show aggregate readiness |
| **Integrated terminal** | Pre-configured with asya-cli, kubectl context |
| **Deploy button** | Run `asya flow deploy` from editor context menu |

The extension is a **local VS Code extension** — it runs in the DS's editor, not in a remote container. It can optionally be used in devcontainers for team standardization.

---

## 5. Security Model

### 5.1 Authentication

Authentication is handled by **standard kubeconfig**, not by a custom auth layer:

| Method | Use Case | Implementation |
|--------|----------|----------------|
| **OIDC via kubelogin** | Corporate SSO for DS | Standard K8s OIDC plugin |
| **Cloud provider auth** | EKS (aws-iam-authenticator), GKE (gcloud) | Native cloud auth |
| **ServiceAccount token** | CI/CD pipelines | Standard K8s token |
| **Client certificates** | Development clusters | Standard kubeconfig |

No custom authentication code needed. The DS's kubeconfig already handles auth.

### 5.2 Authorization

Standard K8s RBAC controls who can do what in which namespace. See Section 3.4 for example RoleBindings.

| Boundary | Enforcement |
|----------|-------------|
| **Lab vs Prod** | K8s RoleBindings: write in lab-*, read-only in prod |
| **Namespace isolation** | K8s RBAC: each DS has RoleBinding in their lab namespace |
| **Secret exposure** | `asya flow deploy --output-dir` generates clean manifests (no secrets extracted from cluster) |
| **Audit logging** | K8s audit log captures all API calls with user identity |
| **Rate limiting** | K8s API priority and fairness (APF) |

### 5.3 Security Advantages Over In-Cluster Service

| Concern | Stagedoor (rejected) | Local tooling (chosen) |
|---------|---------------------|----------------------|
| **Attack surface** | Web service with OIDC, API keys, ingress | None — no cluster-facing service |
| **Credential management** | ServiceAccount with broad AsyncActor CRUD across namespaces | DS's kubeconfig (already exists, already secured) |
| **Privilege escalation** | Compromise stagedoor = cluster-wide AsyncActor access | Compromise DS laptop = only that DS's RBAC scope |
| **Auth bypass** | Custom auth code may have bugs | K8s auth is battle-tested |

---

## 6. GitOps Integration

```
┌─────────────────────────────────────────────────────────────────────┐
│                        GitOps Flow                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Experiment (CLI)                   Production (GitOps)            │
│  ────────────────                   ──────────────────             │
│                                                                     │
│  1. DS compiles flow locally   -->  compiled/routers.py            │
│  2. DS deploys to lab-alice    -->  (not tracked in git)           │
│  3. DS iterates, tests         -->  (ephemeral)                    │
│  4. DS generates manifests     -->  manifests/*.yaml               │
│  5. DS commits to git          -->  git push                       │
│  6. (CLI not involved)         -->  Flux/ArgoCD syncs to prod      │
│  7. DS monitors via kubectl    -->  kubectl get asya -n prod       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Two bridges** to GitOps (see [RFC: Dual-Mode Deployment](../rfc/thoughts-gitops-dev-flow.md)):

- **Bridge A (Generate from source):** `asya flow deploy --output-dir` generates clean YAML files from compiled flow. Primary path for flows.
- **Bridge B (Export from cluster):** `asya export <actor>` sanitizes cluster state into YAML. For hand-created actors that were tweaked in the cluster.

**Supported GitOps tools:**
- **Flux** (recommended): Lightweight, modular
- **ArgoCD**: Richer UI, heavier installation

---

## 7. In-Cluster Actor Spawning (Future)

### 7.1 The Question

With stagedoor removed, all management operations are local (CLI/MCP from DS workstation). But what about **AI agents running as actors inside the cluster** that need to create new actors?

Use cases:
- Orchestrator agent decides it needs a specialist sub-agent
- Dynamic fan-out: flow needs N parallel workers
- Self-healing: actor spawns replacement for degraded peer

### 7.2 Why Standard K8s API Is Sufficient

In the Crossplane architecture, creating an actor is just creating a K8s resource:

```python
# Actor handler that spawns another actor — standard K8s client, no MCP
from kubernetes import client, config

def handle(payload):
    config.load_incluster_config()
    api = client.CustomObjectsApi()
    api.create_namespaced_custom_object(
        group="asya.sh", version="v1alpha1",
        namespace="prod", plural="asyncactors",
        body={
            "apiVersion": "asya.sh/v1alpha1",
            "kind": "AsyncActor",
            "metadata": {"name": f"worker-{payload['task_id']}"},
            "spec": {
                "actor": "dynamic-worker",
                "transport": "sqs",
                "workload": { ... }
            }
        }
    )
```

No MCP, no special API — just K8s client. Crossplane handles the rest (queue, deployment, KEDA).

### 7.3 Deployer Crew Actor (Recommended Pattern)

Rather than giving every actor pod K8s API access, use a **single trusted crew actor** as a gatekeeper:

```
┌──────────────┐     message      ┌──────────────┐     K8s API     ┌──────────────┐
│  Any actor   │────────────────▶│  deployer    │────────────────▶│  AsyncActor  │
│  (no RBAC)   │                 │  (crew actor) │                │  claim       │
└──────────────┘                 │  - validates  │                └──────────────┘
                                 │  - rate limits│
                                 │  - audits     │
                                 │  - has RBAC   │
                                 └──────────────┘
```

**Why crew actor, not MCP endpoint:**
- Fits Asya's choreography model (actors communicate via messages)
- Single ServiceAccount with K8s RBAC (not per-actor)
- Rate limiting and validation at the application level
- Audit trail via envelope tracking (gateway sees all messages)
- No need to expose MCP as an in-cluster service

**deployer crew actor:**
- Lives in `asya-system` namespace (like `happy-end`, `error-end`)
- ServiceAccount with permission to create/delete AsyncActor claims in specific namespaces
- Validates: namespace whitelist, resource quotas, naming conventions
- Audits: logs all creation/deletion requests
- Priority: P4 — implement only when agentic actor spawning is needed

---

## 8. Crossplane Integration

### 8.1 Flavors

Flavors are Crossplane Compositions that platform engineers define:

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  DS creates     │         │  Crossplane     │         │  asya-injector  │
│  AsyncActor     │────────▶│  expands claim  │────────▶│  injects sidecar│
│  claim          │         │  via Composition│         │  into pods      │
│  (flavor: X)    │         │  (flavor X)     │         │                 │
└─────────────────┘         └─────────────────┘         └─────────────────┘
```

- Platform engineers define Compositions (e.g., `llm-heavy`, `fast-router`)
- Each Composition specifies: scaling config, resource limits, node affinities, etc.
- DS selects flavor by name; Crossplane expands to full spec
- Generated manifests remain simple (just `flavor: llm-heavy`)

### 8.2 Observability

Asya does not build observability tooling. DS uses their organization's stack:

| Need | Tool | How |
|------|------|-----|
| **Recent logs** | `kubectl logs` | Direct K8s API (via CLI or VSCode extension) |
| **Historical logs** | Loki, SigNoz, Elasticsearch | Platform team configures log collection (Promtail, Fluent Bit) |
| **Traces** | SigNoz, Jaeger | OTEL instrumentation in sidecar + gateway |
| **Metrics** | Prometheus + Grafana | Sidecar and gateway expose /metrics |
| **Dashboards** | Grafana | Pre-built Asya dashboards (future) |

---

## 9. Open Questions and Future Work

### 9.1 Open Questions

| Question | Status | Notes |
|----------|--------|-------|
| How are flows identified? | Decided: `asya-5av` | Labels (`asya.sh/flow`). See [ADR](../rfc/adr-async-flow-crd-vs-labels.md) |
| How are images built? | Research: `asya-0a` | ConfigMap injection vs CI builds |
| Cross-namespace routing? | Research: `asya-1k0` | `namespace/actor-name` convention |
| Secret management tooling? | Research: `asya-n93` | Encourage best practices via docs/tooling |

### 9.2 Future Enhancements

| Enhancement | Priority | Description |
|-------------|----------|-------------|
| **VSCode extension MVP** | P3 | Flow graph rendering, actor status panel |
| **Local MCP server** | P2 | Wraps asya-cli for AI coding agents |
| **`asya local up`** | P4 | Docker-compose from compiled flow (no K8s required) |
| **Deployer crew actor** | P4 | In-cluster actor spawning for agentic workflows |
| **Deep link to logs** | P3 | Generate links to Grafana/SigNoz with pre-filtered queries |
| **Flow diff view** | P3 | Compare deployed vs local flow versions |
| **Template library** | P3 | Pre-built flow templates (RAG, batch inference, etc.) |

### 9.3 Implementation Phases

| Phase | Scope | Deliverables |
|-------|-------|--------------|
| **Phase 1: CLI** | `asya flow deploy/undeploy/expose` | Flow lifecycle via CLI (bead asya-yh1c) |
| **Phase 2: MCP** | Local MCP server | AI agent integration (wraps CLI) |
| **Phase 3: VSCode** | Extension MVP | Flow visualization, actor status |
| **Phase 4: Agentic** | Deployer crew actor | In-cluster actor spawning |

---

## 10. References

- [ADR: AsyncFlow CRD vs Labels](../rfc/adr-async-flow-crd-vs-labels.md) — Why flows are labels, not CRDs
- [RFC: Dual-Mode Deployment](../rfc/thoughts-gitops-dev-flow.md) — Imperative-to-GitOps promotion workflow
- [RFC: Crossplane Architecture](../rfc/rfc-crossplane.md) — Overall migration from custom operator to Crossplane
- Kubernetes RBAC documentation
- MCP Protocol specification

---

## Appendix A: Related Beads

| Bead ID | Title | Priority |
|---------|-------|----------|
| `asya-yh1c` | Implement asya flow deploy/undeploy/expose CLI commands | P1 |
| `asya-j2vk` | Gateway fsnotify file watcher for config hot-reload | P2 |
| `asya-33qf` | Gateway tool config via singleton ConfigMap | P2 |
| `asya-n93` | Secret management tooling | P2 |
| `asya-0a1` | Image build workflow | P2 |
| `asya-u8x` | Implement asya local: docker-compose from XRDs | P4 |

## Appendix B: Original Stagedoor Design (Superseded)

The original design proposed an in-cluster Go+React service (`asya-stagedoor`) with:
- React SPA for visual flow editing and actor management
- REST API + MCP endpoint for CLI and AI agent integration
- K8s client with scoped RBAC (lab: read-write, prod: read-only)
- Flow compilation proxied to a crew actor via gateway
- Export/sanitization for GitOps promotion

This was superseded because the service was essentially a facade over `kubectl` with a web UI. The facade added infrastructure maintenance (Go backend, React SPA, Helm chart, TLS, ingress, OIDC auth) and security surface (ServiceAccount with cluster-wide access) without capabilities that `kubectl` + standard K8s RBAC don't already provide.

The original design document is preserved in git history for reference.
