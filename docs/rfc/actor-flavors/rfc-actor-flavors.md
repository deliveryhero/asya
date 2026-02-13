# RFC: Actor Flavors — Composable Configuration Presets via EnvironmentConfig

**Status**: Draft
**Created**: 2026-02-10
**Last Updated**: 2026-02-10
**Related**: [rfc-crossplane.md](../rfc-crossplane.md), [thoughts-templated-async-actor-configuration.md](thoughts-templated-async-actor-configuration.md)

---

## 1. Objective

Introduce **Actor Flavors** — reusable, composable configuration presets that reduce AsyncActor boilerplate. Platform engineers define flavors as Crossplane EnvironmentConfigs; developers reference them by name. A custom Crossplane Composition Function (`function-asya-flavors`) provides strategic merge semantics, enabling env var lists from multiple flavors to merge correctly.

---

## 2. Problem Statement

### Repetitive Configuration

AsyncActor specs contain significant boilerplate, especially for common workload patterns:

```yaml
# Every GPU actor repeats this (15+ lines per actor):
spec:
  scaling:
    minReplicas: 1
    maxReplicas: 4
    cooldownPeriod: 600
    queueLength: 2
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          resources:
            requests: { cpu: 2000m, memory: 8Gi }
            limits:   { cpu: 4000m, memory: 16Gi, nvidia.com/gpu: 1 }
        nodeSelector:
          accelerator: nvidia-tesla-t4
        tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
```

### Scale Problem

The Flow DSL compiler generates 10-20+ router actors per flow. Each router needs identical compute, scaling, and runtime configuration. Without flavors, every generated router duplicates the same YAML.

### Multi-Persona Gap

Platform engineers want to set organizational defaults (compute limits, scaling policies). Developers want to focus on their handler logic. Today both must coexist in the same AsyncActor spec with no separation of concerns.

---

## 3. Design

### 3.1 Core Concept

A **flavor** is a partial AsyncActor spec stored as a Crossplane EnvironmentConfig. Actors reference flavors by name. Multiple flavors compose via strategic merge patch.

```yaml
# Platform engineer creates a flavor (once)
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: gpu-t4
  labels:
    asya.sh/flavor: gpu-t4             # required: used by function-asya-flavors
    asya.sh/flavor-dimension: compute  # optional: for discovery (kubectl -l ...)
    asya.sh/flavor-owner: platform     # optional: who manages this flavor
data:                                  # top-level, mirrors AsyncActor spec
  scaling:
    minReplicas: 1
    maxReplicas: 4
    cooldownPeriod: 600
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          resources:
            limits:
              nvidia.com/gpu: "1"
              memory: "16Gi"
          env:
          - name: CUDA_VISIBLE_DEVICES
            value: "0"
        nodeSelector:1
          accelerator: nvidia-tesla-t4
        tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
```

```yaml
# Developer creates an actor (references flavor by name)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-llm
  namespace: prod
spec:
  actor: my-llm
  transport: sqs
  flavors: [gpu-t4, openai-keys]    # <-- composable list of flavors
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-llm:v1
          env:
          - name: ASYA_HANDLER
            value: "model.inference"
          - name: LOG_LEVEL             # actor-level override
            value: "DEBUG"
```

### 3.2 Syntax Unification

Flavors use the **same K8s-native syntax** as AsyncActor specs. A flavor's `data` field mirrors the AsyncActor `spec` structure — same field names, same env var format (list of `{name, value/valueFrom}`), same resource definitions.

This means:
- No new schema to learn
- Copy-paste between actor spec and flavor works
- Existing K8s tooling (linters, IDE autocomplete) applies

### 3.3 Flavor Composition and Merge Semantics

Multiple flavors are applied in list order. The merge follows Kubernetes strategic merge patch semantics:

- **Maps** (resources, nodeSelector, labels): deep merge, later values override
- **Lists with merge key** (env vars by `name`, tolerations by `key`, containers by `name`): merge by key, later values override same-key entries
- **Simple lists** (args, command): replaced entirely by later flavor

```
Merge order (later wins):
  flavor[0] → flavor[1] → ... → flavor[N] → actor inline spec
```

The actor's own inline spec always wins (applied last).

**Example — env var merge across flavors:**

```
Flavor "base":                    Flavor "openai-keys":
  env:                              env:
  - name: LOG_LEVEL                 - name: OPENAI_API_KEY
    value: "INFO"                     valueFrom:
  - name: PYTHONPATH                    secretKeyRef:
    value: "/app"                         name: openai-secrets
                                          key: api-key
                                  - name: OPENAI_MODEL
                                    value: "gpt-4"

Actor spec (inline override):
  env:
  - name: LOG_LEVEL
    value: "DEBUG"                # overrides "INFO" from base flavor

Final merged env:
  - name: LOG_LEVEL        → "DEBUG"        (actor override wins)
  - name: PYTHONPATH       → "/app"         (from base flavor)
  - name: OPENAI_API_KEY   → secretKeyRef   (from openai-keys flavor)
  - name: OPENAI_MODEL     → "gpt-4"        (from openai-keys flavor)
```

### 3.4 Flavor Dimensions

Flavors are orthogonal — each addresses a specific configuration concern. The dimension is implicit in which fields the flavor touches (no explicit `dimension` field needed):

| Dimension | What it controls | Example flavors |
|-----------|-----------------|-----------------|
| compute | CPU, memory, GPU, nodeSelector, tolerations | `cpu-small`, `gpu-a100`, `memory-64gi` |
| scaling | min/max replicas, cooldown, polling, queue length | `scale-to-zero`, `always-on`, `burst-100` |
| scheduling | affinity, topology spread, priority class | `spread-zones`, `colocate`, `preemptible` |
| retry | retry count, backoff strategy, error routing | `no-retry`, `retry-3x-exp` |
| runtime | Python executable, handler mode, env vars, secrets | `conda`, `openai-keys`, `envelope-mode` |

Platform engineers and developers can define custom flavors for any concern. The system doesn't enforce dimension boundaries — a single flavor can touch multiple concerns if needed.

### 3.5 Extensibility

Creating a new flavor requires zero code changes:

1. Create an EnvironmentConfig with label `asya.sh/flavor: <name>`
2. Populate `data` with partial AsyncActor spec fields
3. `kubectl apply`

Any actor can immediately reference the new flavor. No Composition changes, no XRD changes, no function updates.

**Optional labels for discoverability:**

Platform engineers can add optional labels to organize and discover flavors:

| Label | Purpose | Example values |
|-------|---------|---------------|
| `asya.sh/flavor` | Flavor name (required, used by function) | `gpu-t4`, `openai-keys` |
| `asya.sh/flavor-dimension` | Categorize by concern (optional) | `compute`, `scaling`, `runtime`, `retry`, `scheduling` |
| `asya.sh/flavor-owner` | Who manages this flavor (optional) | `platform`, `ml-team`, `developer` |

These labels enable filtering via `kubectl` or future CLI tooling:

```bash
kubectl get environmentconfig -l asya.sh/flavor-dimension=compute
kubectl get environmentconfig -l asya.sh/flavor-owner=platform
```

**Example — platform engineer creates a router flavor for all Flow-generated actors:**

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: flow-router
  labels:
    asya.sh/flavor: flow-router
    asya.sh/flavor-dimension: runtime
data:
  scaling:
    minReplicas: 0
    maxReplicas: 20
    pollingInterval: 5
    cooldownPeriod: 30
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
          resources:
            requests: { cpu: "50m", memory: "64Mi" }
            limits:   { cpu: "200m", memory: "128Mi" }
          env:
          - name: ASYA_HANDLER_MODE
            value: "envelope"
```

### 3.6 workloadRef Compatibility

Flavors work with both workload definition modes:

- **`spec.workload.template`** (inline): Flavor data merges into the template. Composition renders the Deployment.
- **`spec.workloadRef`** (reference, future): Flavor data applies to the referenced Deployment via the mutating webhook. The webhook reads flavor-resolved configuration from an annotation or ConfigMap.

### 3.7 Observability

- `kubectl get asyncactor my-llm -oyaml` shows the original spec with `flavors: [gpu-t4, openai-keys]` (references, not expanded)
- `kubectl get deployment my-llm -oyaml` shows the fully resolved values (expanded env vars, resources, etc.)
- This separation preserves intent (what the user requested) vs. reality (what was rendered)

### 3.8 Flavor Update Propagation

When an EnvironmentConfig (flavor) is updated, Crossplane re-evaluates all Compositions that reference it. Composed resources (Deployments, ScaledObjects) are updated to reflect the new flavor values. This enables fleet-wide configuration changes: update a flavor once, all actors using it converge on next reconciliation.

---

## 4. Implementation Architecture

### 4.1 Crossplane Pipeline

```
AsyncActor Claim
  spec.flavors: [gpu-t4, openai-keys]
       │
       ▼
┌──────────────────────────────────────────┐
│  Composition Pipeline                     │
│                                           │
│  1. function-asya-flavors (custom)        │
│     Reads spec.flavors from XR            │
│     Fetches each EnvironmentConfig by     │
│     name via function-extra-resources     │
│     Applies strategic merge patch:        │
│     - Maps: deep merge                    │
│     - Env vars: merge by name key         │
│     - Tolerations: merge by key           │
│     Applies actor inline spec last (wins) │
│     Writes resolved spec to context       │
│                                           │
│  2. function-go-templating (existing)     │
│     Reads resolved spec from context      │
│     Renders into K8s resources:           │
│     - Deployment (or workloadRef patch)   │
│     - SQS Queue                           │
│     - KEDA ScaledObject                   │
│     - ServiceAccount + IRSA               │
│                                           │
│  3. function-auto-ready (existing)        │
│     Marks composite as ready              │
└──────────────────────────────────────────┘
```

### 4.2 Flavor Fetching

`function-asya-flavors` fetches each EnvironmentConfig individually using `function-extra-resources`. It reads `spec.flavors` from the XR, then for each flavor name, fetches the EnvironmentConfig with label `asya.sh/flavor: <name>`.

This approach (individual fetch per flavor) avoids Crossplane's built-in EnvironmentConfig merge, which would clobber arrays. Each flavor's data is preserved intact for the function to apply strategic merge in the correct order.

There is no fixed max slot limitation — the function iterates over `spec.flavors` dynamically. The XRD enforces `maxItems: 8` as a practical limit, adjustable without code changes.

### 4.3 EnvironmentConfig Data Structure

Each flavor's `data` field is a **partial AsyncActor spec** — same schema, same field names, same nesting. No wrapper keys, no custom format:

```yaml
# EnvironmentConfig gpu-t4
data:
  scaling:
    minReplicas: 1
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: CUDA_VISIBLE_DEVICES
            value: "0"
          resources:
            limits:
              nvidia.com/gpu: "1"
        nodeSelector:
          accelerator: nvidia-tesla-t4

# EnvironmentConfig openai-keys
data:
  workload:
      template:
        spec:
          containers:
          - name: asya-runtime
            env:
            - name: OPENAI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: openai-secrets
                  key: api-key
            - name: OPENAI_MODEL
              value: "gpt-4"
```

This means copy-paste between an AsyncActor `spec` and an EnvironmentConfig `data` works directly. Platform engineers don't need to learn a new schema.

**Why this works without data loss:** `function-asya-flavors` fetches each EnvironmentConfig individually via `function-extra-resources` (by flavor name from `spec.flavors`). It does NOT rely on Crossplane's built-in EnvironmentConfig merge, which would clobber arrays. Each flavor's data is preserved intact, and the function applies strategic merge in `spec.flavors` order.

### 4.4 function-asya-flavors (Custom Composition Function)

A Go Composition Function using `function-sdk-go` and `k8s.io/apimachinery/pkg/util/strategicpatch`.

**Responsibilities:**
1. Read `spec.flavors` from the XR (observed composite resource)
2. Fetch each EnvironmentConfig individually by label `asya.sh/flavor: <name>` via extra resources
3. For each flavor in `spec.flavors` order, read its `data` (a partial AsyncActor spec)
4. Apply strategic merge patch (env by `name`, tolerations by `key`, containers by `name`)
5. Apply actor inline spec as final override (always wins)
6. Write the fully resolved spec to a well-known context key for downstream functions

**Deployment:** Standard Crossplane Function package (OCI image), installed via `Function` CR, runs as a pod in `crossplane-system`. Same operational model as `function-go-templating` and `function-auto-ready`.

**Size estimate:** ~100-150 lines of Go (merge logic). The `strategicpatch` package handles the heavy lifting.

### 4.5 Flavor Catalog Ownership

The Asya framework does **not** ship default flavors in the `asya-crossplane` chart. Flavor definitions are the responsibility of **platform engineers** — they know their infrastructure (GPU node pools, scaling policies, secret providers) better than the framework can prescribe.

A future `asya-quickstart` Helm chart may provide example flavors for common patterns, but strictly as starting-point examples, not production defaults.

**Example flavors a platform team might define:**

| Flavor | Key settings |
|--------|-------------|
| `gpu-t4` | 1-4 replicas, 16Gi memory, 1x T4 GPU, nodeSelector + toleration |
| `always-on` | minReplicas: 1, cooldown: 600s |
| `scale-to-zero` | minReplicas: 0, cooldown: 300s, polling: 30s |
| `burst` | 0-100 replicas, polling: 5s, cooldown: 30s |
| `flow-router` | 0-20 replicas, envelope mode, python:3.13-slim, 128Mi |
| `openai-keys` | OPENAI_API_KEY from secretKeyRef, OPENAI_MODEL |

---

## 5. XRD Schema Changes

Add `flavors` field to the AsyncActor XRD:

```yaml
# In xrd-asyncactor.yaml spec.versions[].schema.openAPIV3Schema.properties
flavors:
  type: array
  maxItems: 8
  items:
    type: string
  description: |
    List of flavor names (EnvironmentConfigs) to compose.
    Applied left-to-right; later flavors override earlier ones.
    Actor inline spec is applied last and always wins.
```

No other XRD changes required. The `flavors` field is optional — actors without it work exactly as today.

---

## 6. Architecture Decision Records

### ADR-1: Composable Orthogonal Flavors vs. Monolithic Flavor Enum

**Status**: Accepted

**Context**: The initial design (see [thoughts document](thoughts-templated-async-actor-configuration.md)) proposed a single `flavor` field with an enum (`default`, `llm-heavy`, `batch-processing`). This requires one Composition per flavor-transport combination and doesn't allow mixing concerns (e.g., GPU compute + conservative scaling).

**Decision**: Use a composable list of orthogonal flavors (`spec.flavors: [gpu-t4, always-on, openai-keys]`). Each flavor is a partial AsyncActor spec addressing a specific concern. Multiple flavors compose via strategic merge patch.

**Consequences**:
- Users can mix and match concerns independently
- Platform engineers can define fine-grained, reusable configuration units
- No combinatorial explosion of Composition variants
- Merge semantics must be well-defined and predictable

### ADR-2: EnvironmentConfigs as Flavor Storage

**Status**: Accepted

**Context**: Multiple storage options were evaluated for flavor definitions:

| Option | Pros | Cons |
|--------|------|------|
| Multiple Crossplane Compositions | Standard pattern, no custom code | One Composition per flavor-transport combo, can't compose |
| Custom CRD (ActorFlavor) | Clean API, typed | Requires custom controller or Composition Function to read |
| ConfigMaps | Simple, namespaced | Not type-safe, no Crossplane-native integration |
| **EnvironmentConfigs** | Crossplane-native, structured data, selected by labels, merged automatically | Cluster-scoped (no namespace isolation), list merge is replacement |

**Decision**: Use EnvironmentConfigs. They integrate natively with Crossplane's composition pipeline, support structured data, and can be selected dynamically via label matching with `FromCompositeFieldPath`.

**Consequences**:
- Flavors are cluster-scoped (same name = same config everywhere). Use naming conventions for environment-specific variants (e.g., `prod-gpu-a100`, `dev-gpu-t4`).
- List merge (env vars) requires `function-asya-flavors` (see ADR-4) because EnvironmentConfig merge replaces arrays.
- Creating a new flavor is just `kubectl apply` of an EnvironmentConfig — zero code changes.

### ADR-3: K8s-Native Syntax for Flavors (No Custom Schema)

**Status**: Accepted

**Context**: Two syntax approaches were considered:

1. **Custom simplified syntax**: `data.env.OPENAI_MODEL: "gpt-4"` (map-based, optimized for merging)
2. **K8s-native syntax**: `data.workload.template.spec.containers[*].env: [{name, value}]` (same as AsyncActor spec)

The custom syntax enables native map merge via EnvironmentConfigs (no list merge problem). But it creates a second schema that users must learn, diverges from K8s conventions, and complicates `valueFrom`/`secretKeyRef` patterns.

**Decision**: Use K8s-native syntax. Flavor data mirrors the AsyncActor spec structure exactly. The list merge challenge is solved by `function-asya-flavors` (ADR-4) rather than by changing the data format.

**Consequences**:
- One syntax to learn (K8s-native everywhere)
- Copy-paste between actor spec and flavor works
- Requires a custom Composition Function for proper list merging
- `valueFrom` / `secretKeyRef` patterns work unchanged

### ADR-4: Custom Composition Function for Strategic Merge

**Status**: Accepted

**Context**: Crossplane cannot natively merge lists of objects by key (issue [crossplane#3335](https://github.com/crossplane/crossplane/issues/3335), closed NOT_PLANNED). The `MergeObjectsAppendArrays` patch policy only appends; it doesn't deduplicate by merge key.

Three approaches to handle env var merging across flavors:

| Approach | Description | Tradeoff |
|----------|-------------|----------|
| Accept list replacement | Last flavor's env list wins entirely | Simple but limits composability |
| Namespace data under flavor keys | Each EnvironmentConfig stores data under its own key; Go template concatenates | No custom code but complex Go templates, name duplication |
| **Custom Composition Function** | Go function applies `strategicpatch` from `k8s.io/apimachinery` | ~100-150 lines of Go, clean merge, deployed inside Crossplane |

**Decision**: Implement `function-asya-flavors` as a custom Crossplane Composition Function. It runs inside Crossplane (pod in `crossplane-system`), uses the same deployment model as existing functions (`function-go-templating`, `function-auto-ready`), and provides correct strategic merge semantics.

**Consequences**:
- Perfect merge behavior: env vars by `name`, tolerations by `key`, containers by `name`
- Must write, test, and maintain ~100-150 lines of Go
- No additional infrastructure beyond what Crossplane already provides
- The function is the only component that understands merge semantics; all other components (XRD, Go templates, EnvironmentConfigs) remain simple

### ADR-5: No Hierarchical Override in v1

**Status**: Accepted

**Context**: A hierarchical model was explored (asya-level defaults in `asya-system` namespace, project-level in actor namespace, actor-level inline). This provides powerful organizational defaults but adds:
- Cross-namespace lookups
- Merge order complexity (3 levels × N flavors)
- Namespace-scoped EnvironmentConfigs (not supported — EnvironmentConfigs are cluster-scoped)

**Decision**: Defer hierarchical override to a future version. v1 supports a flat list of flavors + actor inline override. Platform engineers manage organizational defaults through naming conventions (e.g., `prod-gpu-t4`, `dev-gpu-t4`).

**Consequences**:
- Simpler mental model: flavors are global, actor spec overrides
- No cross-namespace complexity
- Naming conventions required for environment-specific variants
- Future version can add hierarchy via Kyverno or enhanced Composition Function without changing the user-facing API (`spec.flavors` stays the same)

### ADR-6: No Explicit Dimension Field

**Status**: Accepted

**Context**: Early design included a `dimension` field on flavors (`dimension: compute`, `dimension: scaling`) to categorize them. Prefixes (`infra-compute`, `app-runtime`) were also explored.

**Decision**: No dimension field or prefix convention. The "dimension" is implicit in which spec fields the flavor touches. A flavor can span multiple concerns if needed.

**Consequences**:
- Maximum flexibility — flavors are unconstrained partial specs
- No enforced categorization overhead
- Platform engineers can adopt naming conventions voluntarily (e.g., `compute-gpu-t4`, `scaling-burst`) without framework enforcement
- No RBAC boundary between "infra" and "app" flavors (can be added later via Kyverno policies if needed)

### ADR-7: Composition Over Inheritance

**Status**: Accepted

**Context**: Flavor inheritance was considered (e.g., `gpu-a100` extends `gpu-t4` with overrides, via a `parent` field). This would reduce duplication between similar flavors but adds abstraction complexity (inheritance chains, diamond problems, harder to reason about resolved values).

**Decision**: No inheritance. Flavors compose structurally via the `spec.flavors` list. If `gpu-a100` needs most of `gpu-t4`'s config plus overrides, the user lists both: `flavors: [gpu-t4, gpu-a100-overrides]`. Later flavors override earlier ones via strategic merge.

**Consequences**:
- Simpler mental model: each flavor is a standalone partial spec, no hidden parent chain
- Slightly more duplication between similar flavors (acceptable tradeoff)
- Users control merge order explicitly via list ordering
- No framework concept of flavor relationships — just ordered merge

### ADR-8: Inline Configuration Always Wins

**Status**: Accepted

**Context**: When a user specifies `flavors: [gpu-t4]` but inline sets `nvidia.com/gpu: "0"`, should the system warn, error, or silently allow?

**Decision**: Inline configuration always wins, silently. No validation warnings for contradictions between flavors and inline overrides.

**Consequences**:
- Predictable behavior: actor spec is the final authority
- No surprising rejections or warnings when debugging
- Platform engineers cannot enforce "mandatory" flavor settings (acceptable for v1; Kyverno policies can add enforcement later if needed)

---

## 7. Migration and Compatibility

### Backward Compatibility

The `flavors` field is optional. Existing AsyncActors without `flavors` work exactly as today — no migration required.

### Gradual Adoption

1. Platform engineers create EnvironmentConfigs for common patterns
2. Developers add `flavors: [...]` to new actors
3. Existing actors can adopt flavors incrementally (replace inline config with flavor reference)

---

## 8. Future Extensions

- **Hierarchical overrides**: Namespace-scoped flavors via Kyverno mutation policies or enhanced Composition Function
- **Flavor validation**: Webhook that validates flavor references exist before accepting AsyncActor; Kyverno policies for enforcing mandatory flavor settings
- **Flavor catalog**: CLI command (`asya flavor list`) to discover available flavors and their contents
- **Example flavors**: `asya-quickstart` Helm chart with common flavor examples (GPU, burst, always-on) as starting points
- **Flow DSL integration**: `asya flow compile --flavor flow-router` to auto-inject flavor reference into generated actors
- **Additional dimensions**: storage, networking, cost/scheduling as the framework matures

---

## 9. References

- [Crossplane EnvironmentConfigs](https://docs.crossplane.io/latest/composition/environment-configs/)
- [Crossplane Composition Functions](https://docs.crossplane.io/latest/composition/composition-functions/)
- [function-sdk-go](https://github.com/crossplane/function-sdk-go)
- [Kubernetes Strategic Merge Patch](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/update-api-object-kubectl-patch/#use-a-strategic-merge-patch-to-update-a-deployment)
- [crossplane#3335 — Array item merge](https://github.com/crossplane/crossplane/issues/3335)
- [crossplane#4047 — Server-side apply](https://github.com/crossplane/crossplane/issues/4047)
