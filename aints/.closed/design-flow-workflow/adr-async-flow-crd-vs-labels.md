# ADR: AsyncFlow — CRD vs Labels

**Status**: Accepted (Labels)
**Created**: 2026-02-06
**Decision**: Use labels + CLI tooling instead of an AsyncFlow CRD.

---

## 1. Context

Asya actors are flat: each `AsyncActor` claim is an independent unit with its own queue, deployment, and scaling config. The Flow DSL compiler (`asya flow compile`) generates **router actors** that implement branching and sequencing logic, plus references to **processor actors** that perform actual work.

We needed a mechanism to:
- **Group actors** belonging to the same flow (for queries, lifecycle, observability)
- **Deploy and get status of flows** as coherent units (routers + processors + gateway config)
- **Expose flows** as MCP tools via the gateway
- **Support GitOps** (declarative, reproducible, auditable)

Two approaches were evaluated in depth: an AsyncFlow Crossplane XRD, and a label-based convention managed by CLI tooling.

---

## 2. Proposed Architecture: AsyncFlow XRD (Rejected)

### 2.1. Schema

AsyncFlow would be a Crossplane XRD in the `asya.sh` API group with claims:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncFlow
metadata:
  name: order-processing
spec:
  transport: sqs
  entrypoint: validate-order

  # Referenced actors (not owned, must exist)
  processors:
    - actor: validate-order
    - actor: payment-processor

  # Router code — mutually exclusive with routerCodeRefs
  routerCode:
    configMapRef:
      name: order-processing-routers    # existing ConfigMap

  # MCP gateway exposure
  expose:
    enabled: true
    tool:
      name: process-order
      description: "Submit an order for processing"
      parameters:
        type: object
        properties:
          order_id: { type: string }

status:
  phase: Ready            # Creating | Ready | Degraded
  actors:
    ready: 7
    total: 9
  exposed: true
  entrypointQueue: "asya-prod-validate-order"
```

Naming: `AsyncFlow` / `asyncflows` / `asyf`.

### 2.2. Mixed Ownership Model

The composition would create **router** actors (owned, deleted with the flow) and **reference** processor actors (not owned, observed via `managementPolicies: ["Observe"]`). This mirrors the existing `workload` / `workloadRef` pattern in `AsyncActor`.

### 2.3. Three-Phase Implementation

The plan was to progressively enhance AsyncFlow from passive to fully active:

**Phase 1 — Passive XRD**: Schema-only. Composition creates routers and ConfigMaps. No status aggregation, no actor discovery. The XRD is a declaration of intent — "these actors form a flow" — but provides no runtime intelligence. This is similar to how early CRDs worked before controllers were written for them.

**Phase 2 — Semi-active (function-extra-resources)**: Add `function-extra-resources` to the composition pipeline. This Crossplane function reads arbitrary cluster resources during composition, enabling:
- Actor discovery by label selector (`asya.sh/flow=<name>`)
- Status aggregation (count ready/total actors, compute flow phase)
- No custom code — uses existing Crossplane functions (`function-extra-resources` + `function-go-templating`)

**Phase 3 — Fully active (custom composition function)**: Write a Go composition function (~200 LOC) implementing the Crossplane Function SDK. This enables:
- Resolve actors by name (not just label selector)
- M:N flow membership (one actor in multiple flows)
- Lifecycle management with finalizers
- Full status reporting with per-actor readiness

### 2.4. GatewayConfig Aggregator XRD

A hidden singleton XRD (`internal.asya.sh` API group, no claim names, no categories) would aggregate exposed AsyncFlow configs into a single gateway ConfigMap:

```
AsyncFlow (exposed: true)  ─┐
AsyncFlow (exposed: true)  ─┤──► GatewayConfig XRD ──► ConfigMap "gateway-tools"
AsyncFlow (exposed: true)  ─┘         │                        │
                                       │                        ▼
                              function-extra-resources    Gateway pod
                              + function-go-templating    (fsnotify reload)
```

The composition pipeline:
1. `function-extra-resources`: reads AsyncFlow XRs with `expose.enabled: true`
2. `function-go-templating`: aggregates tool definitions from all matching flows
3. Emits a `provider-kubernetes Object` — a ConfigMap mounted into the gateway pod

Hiding mechanisms: no `claimNames` (cluster-scoped only), `internal.asya.sh` API group, no `categories`, RBAC-restricted, auto-created by Helm chart.

### 2.5. Why This Was Attractive

- **Self-documenting**: `kubectl explain asyncflow.spec` describes all fields
- **Single entity**: `kubectl get asyncflow` shows all flows with status columns
- **Validated schema**: XRD enforces structure at admission time
- **Status aggregation**: Phases 2-3 provide real-time flow health
- **Kubernetes-native**: "If it has identity, state, and lifecycle, it should be a resource"

---

## 3. Chosen Architecture: Labels + CLI (Accepted)

### 3.1. Label Convention

Every actor belonging to a flow carries these labels:

| Label | Purpose | Values |
|-------|---------|--------|
| `asya.sh/flow` | Flow membership (1:M) | Flow name (e.g., `order-processing`) |
| `asya.sh/flow-role` | Role within flow | `entrypoint`, `exitpoint`, `router`, `processor` |

Annotations for richer metadata:

| Annotation | Purpose |
|------------|---------|
| `asya.sh/flow-tool` | MCP tool name (if exposed) |
| `asya.sh/flow-description` | Tool description (from flow.py docstring) |

### 3.2. 1:M Constraint

An actor can belong to **at most one flow**. This makes `asya.sh/flow` a reliable foreign key — queryable, indexable, always accurate.

If the same handler logic is needed in multiple flows, the actor is **cloned** (new name, same image/handler, flow-specific scaling config). This is the Kubernetes-native approach — you don't share a Deployment across Services with different scaling requirements either.

### 3.3. CLI Commands

```bash
# Compile flow DSL to routers
asya flow compile order_flow.py --output-dir compiled/

# Deploy: generate manifests and/or apply to cluster
asya flow deploy compiled/ \
  --flow-name order-processing \
  --namespace prod \
  --transport sqs \
  --output-dir manifests/        # for GitOps: generate files

# Expose flow as MCP tool (updates gateway ConfigMap)
asya expose order-processing

# Undeploy: delete all flow resources
asya flow undeploy order-processing -n prod
```

What `asya flow deploy` generates:
1. **AsyncActor manifests for routers** — new resources with `asya.sh/flow` and `asya.sh/flow-role=router` labels
2. **AsyncActor manifests for processors** — creates new or updates existing to add `asya.sh/flow` label
3. **ConfigMap for router code** — `routers.py` content, labeled with `asya.sh/flow`
4. **ConfigMap for flow metadata** — optional, for gateway exposure

### 3.4. GitOps Workflow

The CLI generates **manifest files**, not cluster mutations:

```
DS laptop                         Git repo                    Cluster
───────                          ────────                    ───────
asya flow compile flow.py
        │
        ▼
asya flow deploy compiled/ \
  --output-dir manifests/
        │
        ▼
manifests/
├── router-start.yaml          ──► git add && commit ──► ArgoCD ──► kubectl apply
├── router-line-4-if.yaml              │
├── validate-order.yaml                │
├── payment-processor.yaml             │
└── routers-configmap.yaml             ▼
                                  Source of truth
```

For experimentation (no GitOps): omit `--output-dir`, CLI applies directly to cluster.

### 3.5. Gateway Tool Registration

Instead of a GatewayConfig aggregator XRD, the gateway mounts a singleton ConfigMap (`gateway-tools`). The CLI updates it:

```bash
asya expose order-processing
# 1. Finds entrypoint actor by label: asya.sh/flow-role=entrypoint
# 2. Reads tool name from annotation (or derives from flow name)
# 3. Detects description from flow.py docstring
# 4. Detects parameters from flow.py function signature
# 5. Patches gateway-tools ConfigMap
# 6. Kubelet syncs to mounted volume → fsnotify → gateway reloads
```

---

## 4. Decision Rationale

### 4.1. Flow Topology Is an Application Concern

The critical insight: **flow routing logic lives in `routers.py` — Python code inside the actor, not Kubernetes resources**. The K8s level only needs to know "which actors participate in this flow" (an unordered set with role annotations), not the flow's branching structure, conditions, or sequencing.

An AsyncFlow CRD would replicate application-level topology at the Kubernetes level — creating a dual source of truth that nobody would read directly (it's generated by `asya-cli`). This violates the principle of having one authoritative source per concern.

### 4.2. XRD Has the Same GitOps Problem for Referenced Actors

A key discovery during design: even with an AsyncFlow XRD, referenced processor actors still need `asya.sh/flow` labels in their manifests for searchability. The XRD can set labels at runtime via composition, but then GitOps manifests in git don't match cluster state (drift). To avoid drift, you must update processor manifests in git anyway — the same work as the labels-only approach.

The XRD adds a layer of indirection without actually simplifying the GitOps story for referenced (non-owned) actors.

### 4.3. Passive CRD Provides No Status Anyway

A passive XRD (Phase 1) has no controller logic — no status aggregation, no health checks, no drift detection. It's a schema with no runtime intelligence. The value proposition of a CRD ("single entity with status") requires Phases 2-3, which are significant engineering effort for uncertain payoff at this stage.

### 4.4. Labels Naturally Model Unordered Set Membership

The relationship between a flow and its actors is: "these actors participate in this flow." This is an **unordered set membership** — exactly what Kubernetes labels are designed for. Adding role distinctions (`entrypoint`, `router`, `processor`) via `asya.sh/flow-role` provides the necessary structure without a CRD.

Discovery works natively:
```bash
kubectl get asya -l asya.sh/flow=order-processing
kubectl get asya -l asya.sh/flow=order-processing,asya.sh/flow-role=entrypoint
kubectl delete asya -l asya.sh/flow=order-processing
```

### 4.5. 1:M Makes Labels Reliable

The decision to constrain actor-flow relationships to 1:M (one actor belongs to at most one flow) is what makes the labels-only approach viable. With M:N, `asya.sh/flow` would hold only one of potentially many flow names — unreliable for queries. With 1:M, the label is a true foreign key.

Actor cloning (deploying the same handler logic under a different actor name) is not a workaround but the correct Kubernetes pattern: different flows will likely need different scaling, resources, and queue configs for the same handler logic anyway.

### 4.6. Premature Abstraction Risk

We don't yet know:
- What status fields flows actually need in production
- Whether flows should compose (flow-of-flows)
- What the gateway exposure schema should look like at scale
- What OTEL tracing needs from flow identity
- Whether 1:M is the right long-term constraint

Committing to a CRD schema now risks building the wrong abstraction. Labels establish the **convention** (`asya.sh/flow=name`). A future CRD can adopt this convention and add structure on top — the migration is additive and non-breaking.

---

## 5. What We Lose

| Capability | Impact | Mitigation |
|-----------|--------|------------|
| `kubectl get asyncflow` | No single-resource view of flows | `kubectl get asya -l asya.sh/flow=X` |
| `kubectl explain asyncflow.spec` | No self-documenting schema | `asya flow --help` provides discoverability |
| Admission validation | No schema enforcement on flow structure | CLI validates during `asya flow deploy` |
| Status aggregation | No real-time flow health | Query individual actors; passive CRD wouldn't have status either |
| Single-resource deletion | Must use label selector | `kubectl delete asya -l asya.sh/flow=X` or `asya flow undeploy X` |
| GatewayConfig XRD | No automatic aggregation | CLI updates singleton ConfigMap directly |

---

## 6. What We Gain

| Benefit | Detail |
|---------|--------|
| Zero new CRDs | No XRD, composition, or provider-kubernetes Objects to maintain |
| No three-phase rollout | Labels work immediately — no progressive enhancement needed |
| Simpler gateway | Singleton ConfigMap updated by CLI, no aggregation composition |
| GitOps-native | Manifest files with labels in git — ArgoCD/Flux apply directly |
| Reduced user cognitive load | No new resource type to learn; just labels on existing AsyncActors |
| Future design freedom | Can introduce AsyncFlow CRD later with real usage data informing the schema |
| Flat actor mesh | Actors remain the primary abstraction; flows are a labeling convention, not a hierarchy |

---

## 7. Core Insights

These observations shaped the decision and should inform future revisitation:

**Labels as stable API.** The label convention (`asya.sh/flow=name`) is the contract. Whether a CLI or a CRD controller manages that label is an implementation detail. This is how the K8s ecosystem works: labels like `app.kubernetes.io/name` existed before any controller enforced them. Establishing the convention now enables a future CRD to adopt it without breaking changes.

**Generator vs Controller.** `asya flow deploy` is a generator (like `helm template` or `kubectl create deployment`), not a controller. It produces declarative resources. The controllers (Crossplane composition for AsyncActor, ArgoCD for GitOps) handle reconciliation. This separation keeps the CLI stateless and the reconciliation loop in proven systems.

**Layer separation.** Routing topology (which actor calls which, under what conditions) is application logic in `routers.py`. Infrastructure grouping (which actors participate in a flow) is a Kubernetes concern addressed by labels. AsyncFlow CRD would bridge these layers, creating dual sources of truth. Keeping them separate means each layer is independently evolvable.

**The CRD question.** "If something has identity, state, and lifecycle, it should be a resource" — but this applies only when cluster-level reconciliation adds value. Flows have identity (the label value) and lifecycle (deploy/undeploy), but their "state" is the aggregate state of their constituent actors, which already have individual status tracking. A CRD adds value when you need **automated reactions** to state changes (auto-healing, drift detection, cascading status). Until that need is demonstrated, the CRD is overhead.

**1:M is the enabler.** The M:N vs 1:M constraint on actor-flow membership is the pivotal decision. M:N makes labels unreliable (a label key holds one value) and requires a junction table (CRD). 1:M makes labels reliable and eliminates the need for the junction table entirely. Actor cloning (deploying the same handler under a flow-specific name) is not a cost — it's the correct pattern, since different flows need different scaling/resource configs for the same logic.

**YAGNI at the CRD level.** The label convention supports a future CRD without requiring it now. The escape hatch: introduce an AsyncFlow CRD whose composition reads and manages `asya.sh/flow` labels. The migration is: "wrap existing labeled resources in a CRD." No schema to migrate, no data to convert — just add a new resource that manages what the CLI used to manage.

---

## 8. Migration Path to AsyncFlow CRD (If Needed)

If cluster-level reconciliation becomes necessary (status aggregation, auto-healing, drift detection), the CRD can be introduced incrementally:

1. Define AsyncFlow XRD with a schema informed by real usage patterns
2. Composition creates/observes actors using the same `asya.sh/flow` label convention
3. `asya flow deploy` generates AsyncFlow YAML instead of individual actor manifests
4. Existing label-based queries (`kubectl get asya -l asya.sh/flow=X`) continue working
5. GatewayConfig XRD can aggregate AsyncFlows instead of the CLI updating a ConfigMap

Triggers for this migration:
- Multiple teams sharing clusters need RBAC on flow-level operations
- SRE requires `kubectl get asyncflow` dashboard with status columns
- Flow health needs automated alerting (not just manual queries)
- Flow lifecycle events need to trigger external systems (webhooks, notifications)

---

## 9. References

- [RFC: Crossplane Architecture](rfc-crossplane.md) — Overall migration from custom operator to Crossplane
- [RFC: Dual-Mode Deployment](thoughts-gitops-dev-flow.md) — Imperative-to-GitOps promotion workflow
- [Flow Compiler Architecture](../architecture/asya-flow.md) — How flow DSL compiles to router actors
- Crossplane [function-extra-resources](https://github.com/crossplane-contrib/function-extra-resources) — Reads arbitrary K8s resources during composition
- Crossplane [provider-kubernetes](https://github.com/crossplane-contrib/provider-kubernetes) — Creates K8s resources from compositions
