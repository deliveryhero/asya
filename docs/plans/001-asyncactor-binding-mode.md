# ADR-001: AsyncActor Binding Mode for Third-Party Workload Integration

**Status:** Approved
**Date:** 2025-11-09
**Authors:** Asya🎭 Core Team
**Deciders:** Project Maintainers

## Context

### Problem Statement

Asya🎭's current AsyncActor CRD operates in a single mode: it creates and owns workloads (Deployment/StatefulSet) with injected sidecar containers. This works well for standalone async actors but prevents integration with existing Kubernetes-native AI/ML platforms that manage their own workloads.

**Key integrations we need to support:**

1. **KAITO (Kubernetes AI Toolchain Operator)**: Automates AI model deployment with GPU provisioning
2. **KServe**: Production ML serving platform with model versioning and canary deployments
3. **KubeRay**: Ray distributed computing framework with multi-GPU inference
4. **NVIDIA Triton**: High-performance GPU inference server
5. **Seldon Core, BentoML, vLLM**: Additional ML serving platforms

**Current limitation:**

These platforms create and manage their own Deployments. AsyncActor cannot inject sidecars into existing workloads - it only creates new ones.

**Example user scenario:**

```yaml
# User deploys model with KAITO
apiVersion: kaito.sh/v1alpha1
kind: Workspace
metadata:
  name: phi-3-embeddings
spec:
  inference:
    preset:
      name: phi-3-mini-4k-instruct

# KAITO creates Deployment: phi-3-embeddings
# User wants to add Asya🎭 async capabilities (message queuing, scale-to-zero)
# Currently: NO WAY to do this without manually patching Deployment
```

### Requirements

1. **Support two deployment patterns:**
   - Pattern A: Asya🎭 creates workload (current behavior)
   - Pattern B: Asya🎭 binds to existing workload (new requirement)

2. **Preserve existing functionality:**
   - No breaking changes to current AsyncActor users
   - Standalone mode continues to work unchanged

3. **Handle workload ownership properly:**
   - Third-party controllers own their workloads
   - Asya🎭 only adds sidecar injection and KEDA autoscaling
   - No ownership conflicts

4. **Support CRD-based workloads:**
   - Resolve KAITO Workspace → Deployment
   - Resolve KServe InferenceService → Knative Service
   - Direct Deployment/StatefulSet references

5. **Maintain operational simplicity:**
   - Clear status reporting
   - Easy debugging
   - Predictable behavior

6. **Runtime container serves dual purpose:**
   - Standalone mode: `asya-runtime` runs user handler directly
   - Binding mode: `asya-runtime` runs user handler as REST adapter/proxy
   - User configures handler to forward requests to inference server
   - No modification of existing model containers
   - Standard container name: `asya-runtime` in both modes

## Decision Drivers

- **Simplicity**: Minimize API surface and operational complexity
- **User experience**: Single interface for all async actors
- **Robustness**: Handle conflicts with third-party controllers gracefully
- **Extensibility**: Support future integration targets
- **Performance**: Avoid watch storms on large clusters
- **Maintainability**: Keep reconciler logic manageable

## Options Considered

### Option 1: Mutating Admission Webhook

**Approach:** Intercept third-party resource creation (KAITO Workspace, KServe InferenceService) and inject sidecar via webhook.

**Implementation:**
```yaml
# User creates KAITO Workspace with annotation
apiVersion: kaito.sh/v1alpha1
kind: Workspace
metadata:
  name: phi-3
  annotations:
    asya.sh/enable: "true"
    asya.sh/transport: "rabbitmq"
spec:
  inference:
    preset:
      name: phi-3-mini-4k-instruct

# MutatingWebhook intercepts Workspace creation
# Modifies pod template to inject sidecar
# Creates ScaledObject separately
```

**Pros:**
- Zero changes to AsyncActor CRD
- No ownership conflicts (third-party controllers own resources)
- Works with any K8s workload
- Annotation-based: simple, declarative

**Cons:**
- Requires webhook infrastructure (certs, HA, cert rotation)
- Harder to debug (mutation happens transparently)
- Must implement webhook for each integration target
- Annotation sprawl for configuration
- Webhook failures block resource creation

**Verdict:** ❌ Rejected - operational complexity too high, debugging difficult

---

### Option 2: Single AsyncActor CRD with Optional `workloadRef`

**Approach:** Extend AsyncActor with mutually exclusive fields: `workload` (create) OR `workloadRef` (bind).

**Implementation:**
```yaml
# Standalone mode (existing behavior)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: standalone-actor
spec:
  transport: rabbitmq
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13

---
# Binding mode (new behavior)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: kaito-binding
spec:
  transport: rabbitmq

  # Reference existing workload
  workloadRef:
    apiVersion: kaito.sh/v1alpha1
    kind: Workspace
    name: phi-3-embeddings

  # Runtime configuration for binding mode
  # Runtime container acts as proxy/adapter to existing inference server
  runtime:
    image: asya-rest-adapter:latest
    handler: "adapters.kaito_openai.forward"
    targetURL: "http://phi-3-inference:8080"

  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 100
```

**Pros:**
- Single CRD for all use cases
- Unified management: `kubectl get asyas` shows everything
- Simple RBAC: one resource type
- Lower learning curve: one API to learn
- Mode is implicit based on fields set
- Easy to add future modes (serviceRef, functionRef)
- Shared status model and metrics
- No webhook infrastructure needed

**Cons:**
- More complex reconciler (branches on mode)
- Must watch ALL Deployments (with predicate filtering)
- Ownership ambiguity (two controllers modifying same Deployment)
- Potential patch conflicts with third-party controllers
- API validation more complex (mutual exclusion)
- Status semantics differ between modes

**Verdict:** ✅ **SELECTED** - unified interface outweighs complexity

---

### Option 3: Separate AsyncActor + AsyncBinding CRDs

**Approach:** Create two CRDs with focused responsibilities.

**Implementation:**
```yaml
# AsyncActor: creates workload (unchanged)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: standalone-actor
spec:
  transport: rabbitmq
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13

---
# AsyncBinding: binds to existing workload (new CRD)
apiVersion: asya.sh/v1alpha1
kind: AsyncBinding
metadata:
  name: kaito-binding
spec:
  transport: rabbitmq
  targetRef:
    apiVersion: kaito.sh/v1alpha1
    kind: Workspace
    name: phi-3-embeddings
  runtime:
    targetService:
      name: phi-3-inference
      port: 8080
    image: asya-rest-adapter:latest
    handler: "adapters.kaito_openai.forward"
  scaling:
    enabled: true
```

**Pros:**
- Clear separation of concerns
- Simple reconcilers (single responsibility)
- Clear ownership model
- Easy to reason about
- Independent API evolution
- Better error messages (mode-specific)

**Cons:**
- Fragmented management: need two `kubectl get` commands
- More CRDs to maintain
- RBAC more verbose (two resource types)
- Code duplication (shared injection logic)
- Higher learning curve (when to use which?)
- More resources in etcd

**Verdict:** ❌ Rejected - operational fragmentation outweighs architectural purity

---

### Option 4: Sidecar Controller Pattern (Composable Primitives)

**Approach:** Create low-level primitives (SidecarInjector, QueueScaler) with AsyncActor as high-level orchestrator.

**Implementation:**
```yaml
# Low-level: SidecarInjector
apiVersion: asya.sh/v1alpha1
kind: SidecarInjector
metadata:
  name: phi3-sidecar
spec:
  targetRef:
    kind: Deployment
    name: phi-3
  transport: rabbitmq

---
# Low-level: QueueScaler
apiVersion: asya.sh/v1alpha1
kind: QueueScaler
metadata:
  name: phi3-scaler
spec:
  targetRef:
    kind: Deployment
    name: phi-3
  transport: rabbitmq
  minReplicas: 0
  maxReplicas: 100

---
# High-level: AsyncActor (orchestrates primitives)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: standalone
spec:
  workload: {...}
  # Operator creates SidecarInjector + QueueScaler internally
```

**Pros:**
- Maximum flexibility and composability
- Single responsibility per CRD
- Easy to test individually
- Platform teams can mix/match primitives

**Cons:**
- Over-engineered for current needs
- Steeper learning curve
- More CRDs (3+)
- More reconcilers to maintain
- Complexity overhead

**Verdict:** ❌ Rejected - unnecessary complexity for current requirements

---

## Decision

**We choose Option 2: Single AsyncActor CRD with optional `workloadRef` field.**

### Rationale

1. **Unified management interface is critical:**
   - Platform operators need single view: `kubectl get asyas`
   - Monitoring dashboards query one resource type
   - Alerts and metrics collection simpler

2. **User experience prioritized:**
   - Single CRD to learn: "AsyncActor = async capabilities"
   - Mode is implicit (less cognitive load)
   - RBAC policies simpler

3. **Cons are mitigatable:**
   - Watch performance: Use predicate filtering on Deployment watches
   - Conflicts: Implement conflict detection with exponential backoff
   - Reconciler complexity: Extract shared logic to packages
   - API clarity: Comprehensive CEL validation + clear docs

4. **Future extensibility:**
   - Easy to add new modes without CRD proliferation
   - Single status model evolves together

5. **Operational simplicity:**
   - One resource type for backup/restore
   - One API version to manage
   - One set of kubectl commands to remember

### Trade-offs Accepted

We accept the following trade-offs:

**Reconciler complexity:**
- Single reconciler handles two modes (standalone + binding)
- Mitigated by: Extracting shared logic to `pkg/injection`, `pkg/keda` packages

**Watch performance:**
- Must watch ALL Deployments in cluster (not just owned)
- Mitigated by: Predicate filtering on `asya.sh/managed-by` annotation

**Ownership ambiguity:**
- Two controllers modifying same Deployment (e.g., KAITO + Asya🎭)
- Mitigated by: Non-controller owner references, conflict detection with backoff

**API validation:**
- Complex mutual exclusion rules (`workload` XOR `workloadRef`)
- Mitigated by: CEL validation with clear error messages

## Consequences

### Positive

- Users have single interface for all async actors (standalone + bindings)
- Platform operators see complete picture with one command
- Metrics and monitoring simplified (single resource type)
- RBAC policies cleaner (one resource type)
- Future modes (serviceRef, functionRef) can be added without new CRDs

### Negative

- Reconciler branching logic required (mode detection)
- Watch configuration more complex (must watch non-owned Deployments)
- Potential conflicts with third-party controllers (requires detection + backoff)
- Status semantics differ between modes (must document clearly)

### Neutral

- Code must be well-structured (shared packages for injection, KEDA, status)
- Documentation must clearly explain two modes
- Validation messages must guide users to correct usage

## Implementation Requirements

To make Option 2 work reliably, we MUST implement:

### 1. Predicate Filtering (Performance)
```go
Watches(
    &appsv1.Deployment{},
    handler.EnqueueRequestsFromMapFunc(r.findAsyncActorsForDeployment),
    builder.WithPredicates(predicate.NewPredicateFuncs(func(obj client.Object) bool {
        annotations := obj.GetAnnotations()
        return annotations != nil && annotations["asya.sh/managed-by"] != ""
    })),
)
```

### 2. Conflict Detection with Backoff (Robustness)
```go
// In AsyncActorStatus
ConflictCount int `json:"conflictCount,omitempty"`
LastConflictTime *metav1.Time `json:"lastConflictTime,omitempty"`

// In reconciler
if conflictDetected && asya.Status.ConflictCount > 5 {
    // Stop fighting external controller, report error
    return ctrl.Result{}, nil
}
```

### 3. Clear Status Conditions (Debuggability)
```go
// Add mode indicator
Mode string `json:"mode,omitempty"`  // "Standalone" or "Binding"

// Add resolved target for binding mode
ResolvedTarget *WorkloadReference `json:"resolvedTarget,omitempty"`
```

### 4. Comprehensive CEL Validation (API Clarity)
```go
// +kubebuilder:validation:XValidation:rule="(has(self.workload) && !has(self.workloadRef)) || (!has(self.workload) && has(self.workloadRef))", message="Exactly one of 'workload' or 'workloadRef' must be set"
```

### 5. Documentation Structure
- Clear mode selection guide in docs
- Binding mode examples for each integration (KAITO, KServe, etc.)
- Troubleshooting guide for conflicts

## Migration Path

### For Existing Users
- No changes required
- Existing AsyncActors continue working unchanged
- `workload` field remains primary mode

### For New Integrations
- Use `workloadRef` for binding to KAITO, KServe, etc.
- Follow integration guides in docs

### Future Evolution

If Option 2 proves problematic in production:

**Fallback to Option 3 (Split CRD):**
1. Create AsyncBinding CRD
2. Add deprecation warning to `AsyncActor.workloadRef`
3. Provide migration tool
4. Eventually remove `workloadRef` in v2alpha1 (breaking change)

Migration would be straightforward:
```bash
# Automated migration
kubectl get asyncactors -o json | \
  jq '.items[] | select(.spec.workloadRef != null)' | \
  # Transform to AsyncBinding format
  kubectl apply -f -
```

## References

- Integration requirements: `docs/plans/integrations.md`
- KAITO documentation: https://github.com/Azure/kaito
- KServe documentation: https://kserve.github.io/website/
- KEDA documentation: https://keda.sh/

## Related Documents

- Design document: `docs/plans/asyncactor-binding-mode-design.md`
- Implementation tracking: GitHub issue #TBD
