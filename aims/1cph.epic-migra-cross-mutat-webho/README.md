---
title: "Epic: Migrate to Crossplane + Mutating Webhook Architecture"
status: open
priority: 1 # high
type: epic
---

Replace the custom ~16K LOC asya-operator with a Crossplane-based declarative control plane and a lightweight mutating webhook for sidecar injection.

## Motivation

- **Maintenance burden**: Current operator requires ~400 LOC per transport, complex reconciliation logic
- **Instability**: Custom reconciliation loops prone to edge cases and race conditions
- **Drift ignorance**: Manual changes to cloud resources not automatically corrected

## Solution

1. **Crossplane Compositions**: Declarative infrastructure management (SQS queues, KEDA ScaledObjects, Deployments)
2. **Mutating Webhook (asya-injector)**: Lightweight Go webhook for sidecar injection at pod creation

## Scope

- AWS SQS transport (priority 1)
- Both workload (template) and workloadRef support
- KEDA autoscaling with scale-to-zero
- Pod health status via labels

## Out of Scope (future work)

- Other transports (RabbitMQ, Pub/Sub, Kafka, Azure Service Bus, NATS)
- Actor warm-up before scale-to-zero (see thoughts-actor-warm-up.md)
- Composition Functions for replica count status

## RFC: Crossplane-Based Actor Management

### 1. Objective

Evolve Asya from a custom ~16K LOC Go operator into a declarative, cloud-native control plane using **Crossplane** for infrastructure orchestration and a **Mutating Webhook** for workload injection. This reduces maintenance burden, increases stability through battle-tested components, and provides built-in drift detection.

---

### 2. Problem Statement

#### Current State (asya-operator)

The `asya-operator` is a monolithic Kubebuilder-based controller with significant complexity:

| Concern | Current Implementation | Pain Points |
|---------|------------------------|-------------|
| **Queue Management** | ~400 LOC per transport (SQS, RabbitMQ) | Duplicated code, manual drift handling |
| **Workload Creation** | ~200 LOC sidecar injection | Tightly coupled, hardcoded configs |
| **KEDA Integration** | ~300 LOC ScaledObject management | Race conditions with HPA, retry logic |
| **Status Computation** | ~250 LOC with 17 status types | Brittle pod message parsing |
| **Credential Management** | ~130 LOC namespace translation | Complex secret copying logic |
| **Main Reconciliation** | 9+ sequential steps, 185 LOC | Hard to reason about, hidden dependencies |

**Total**: ~16,000 lines of Go code across 32 files.

#### Key Issues

1. **Maintenance Burden**: Adding new transports requires ~400 lines of duplicated code per implementation
2. **Instability**: Custom reconciliation loops are prone to edge cases, race conditions, and subtle bugs
3. **Drift Ignorance**: Manual changes to cloud resources (e.g., SQS queue settings) are not automatically corrected
4. **GitOps Conflicts**: Patching Deployments after creation causes pod restarts and sync-fights with ArgoCD/Flux

---

### 3. Proposed Architecture

#### High-Level Design

```
┌─────────────────────────────────────────────────────────────────┐
│                     User Creates                                 │
│                                                                  │
│   apiVersion: asya.sh/v1alpha1                                  │
│   kind: AsyncActor        ◄── CompositeResource (XR)            │
│   spec:                                                          │
│     transport: sqs                                               │
│     workload: { ... }     # OR workloadRef: my-deployment       │
│     scaling: { min: 0, max: 10 }                                │
│                                                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Crossplane Composition                          │
│                  (one per transport: sqs, rabbitmq, etc.)        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ SQS Queue   │  │ SQS DLQ     │  │ KEDA ScaledObject       │  │
│  │ (provider-  │  │ (provider-  │  │ (provider-kubernetes)   │  │
│  │  aws)       │  │  aws)       │  │                         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│                                                                  │
│  ┌─────────────────────────────┐  ┌─────────────────────────┐   │
│  │ Deployment (if workload)   │  │ ServiceAccount + IRSA   │   │
│  │ (provider-kubernetes)      │  │ (provider-aws IAM)      │   │
│  └─────────────────────────────┘  └─────────────────────────┘   │
│                                                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Mutating Webhook (asya-injector)                │
├─────────────────────────────────────────────────────────────────┤
│  Trigger: Pod creation with label asya.sh/inject=true           │
│  Action:  Query AsyncActor XR → Inject sidecar + runtime        │
└─────────────────────────────────────────────────────────────────┘
```

#### Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|----------------|----------------|
| **AsyncActor XRD** | User-facing API definition | Crossplane CompositeResourceDefinition |
| **Composition (per transport)** | Map AsyncActor → cloud resources | Crossplane Composition YAML |
| **provider-aws** | Manage SQS queues, IAM, DLQ | Upbound provider-aws |
| **provider-kubernetes** | Manage Deployment, KEDA, ConfigMap | Crossplane provider-kubernetes |
| **asya-injector** | Sidecar injection at pod creation | Go Mutating Admission Webhook |

---

### 4. The AsyncActor XRD (API Design)

#### Spec Schema

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-analyzer
  namespace: prod
spec:
  # Transport configuration (required)
  transport: sqs  # sqs | rabbitmq | pubsub | kafka | servicebus | nats

  # Workload definition (one of workload or workloadRef required)
  workload:  # Crossplane creates and owns the Deployment
    kind: Deployment  # or StatefulSet
    replicas: 1
    template:
      spec:
        containers:
          - name: runtime
            image: my-app:v1.0
            env:
              - name: ASYA_HANDLER
                value: my_module.process

  workloadRef:  # User owns the Deployment, just inject sidecar
    name: my-existing-deployment
    kind: Deployment

  # KEDA autoscaling (optional, enabled by default)
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    pollingInterval: 30
    cooldownPeriod: 300

  # Sidecar configuration (optional overrides)
  sidecar:
    image: asya/sidecar:v1.0  # default
    resources:
      limits:
        memory: 128Mi
        cpu: 100m

  # Runtime configuration (optional)
  runtime:
    pythonExecutable: /usr/bin/python3  # default
    handlerMode: payload  # payload | envelope
```

#### Status Schema

```yaml
status:
  # Standard Crossplane conditions
  conditions:
    - type: Ready
      status: "True"
      reason: Available
    - type: Synced
      status: "True"

  # Phase for quick status (derived from conditions)
  phase: Running  # Creating | Running | Napping | ScalingUp | ScalingDown | Degraded | Failed

  # Infrastructure status
  infrastructure:
    queue: Ready      # Ready | Creating | Error
    keda: Ready       # Ready | Creating | Disabled | Error
    workload: Ready   # Ready | Creating | Error

  # Replica information (if Composition Function enabled)
  replicas:
    ready: 3
    desired: 3
    failing: 0
```

#### Status Phases

| Phase | Meaning | Condition |
|-------|---------|-----------|
| **Creating** | Infrastructure being provisioned | queue/keda/workload not ready |
| **Running** | Healthy and processing | ready > 0, no failing pods |
| **Napping** | Scaled to zero, healthy infrastructure | ready = 0, KEDA scaled down, infra OK |
| **ScalingUp** | KEDA increasing replicas | desired > ready |
| **ScalingDown** | KEDA decreasing replicas | desired < ready |
| **Degraded** | Partially healthy | 0 < ready < desired, some pods failing |
| **Failed** | Completely broken | ready = 0 AND (failing > 0 OR infra error) |

---

### 5. Label Taxonomy

#### Pod Labels (set by Webhook during injection)

| Label | Example | Purpose |
|-------|---------|---------|
| `asya.sh/actor` | `text-analyzer` | Actor identifier (matches queue suffix, routing key) |
| `asya.sh/inject` | `true` | Signals webhook to inject sidecar |
| `asya.sh/transport` | `sqs` | Which transport this actor uses |
| `asya.sh/actor-type` | `user` / `system` | Distinguish user actors from crew (happy-end, error-end) |

#### Deployment Labels (set by Crossplane Composition)

| Label | Example | Purpose |
|-------|---------|---------|
| `asya.sh/actor` | `text-analyzer` | Actor name (matches pods) |
| `asya.sh/managed-by` | `crossplane` | Ownership tracking |
| `asya.sh/transport` | `sqs` | Transport type |

#### Future Labels

| Label | Purpose |
|-------|---------|
| `asya.sh/flow` | Flow DSL integration (which flow this actor belongs to) |
| `asya.sh/version` | Canary/blue-green deployment support |
| `asya.sh/handler` | Handler module for debugging |

#### Important Note

- AsyncActor/Deployment names can be arbitrary
- `asya.sh/actor` label MUST match the queue suffix - this is the primary routing key
- Example: `asya.sh/actor=text-analyzer` → queue `asya-prod-text-analyzer`

---

### 6. The Mutating Webhook (asya-injector)

#### Trigger Conditions

The webhook intercepts Pod creation when:
1. Pod has label `asya.sh/inject: "true"`
2. Pod is in a namespace with Asya enabled (optional namespace selector)

#### Injection Flow

```
Pod Creation Request
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    asya-injector                             │
├─────────────────────────────────────────────────────────────┤
│ 1. Check label: asya.sh/inject=true                         │
│ 2. Read label: asya.sh/actor=X                              │
│ 3. Query: GET AsyncActor X in pod's namespace               │
│ 4. Check: AsyncActor.status.conditions[Ready] == True       │
│    - If not ready: reject with retry (infrastructure not up)│
│ 5. Extract configuration from AsyncActor spec:              │
│    - sidecar.image, sidecar.resources                       │
│    - runtime.pythonExecutable, runtime.handlerMode          │
│    - transport type for env vars                            │
│ 6. Inject into pod:                                         │
│    - Sidecar container with probes                          │
│    - Runtime ConfigMap volume mount                         │
│    - Shared socket volume                                   │
│    - Environment variables (queue URL, transport config)    │
│ 7. Return mutated pod                                       │
└─────────────────────────────────────────────────────────────┘
```

#### Injected Resources

| Resource | Description |
|----------|-------------|
| **Sidecar container** | `asya-sidecar` with liveness/readiness probes |
| **Socket volume** | `emptyDir` for Unix socket communication |
| **Runtime volume** | ConfigMap mount at `/opt/asya/asya_runtime.py` |
| **Tmp volume** | `emptyDir` for runtime temporary files |
| **Environment variables** | `ASYA_QUEUE_URL`, `ASYA_TRANSPORT`, `ASYA_HANDLER`, etc. |

#### workloadRef Behavior

For `workloadRef` (user-managed workloads):
1. User must add `asya.sh/inject: "true"` and `asya.sh/actor: X` labels to their pod template
2. User must trigger pod recreation (`kubectl rollout restart`) after creating AsyncActor
3. Webhook injects sidecar on new pod creation
4. Existing pods are NOT modified (admission webhooks are create-time only)

---

### 7. Crossplane Composition (SQS)

#### Composed Resources

For `transport: sqs`, the Composition creates:

```yaml
# 1. SQS Queue (main actor queue)
apiVersion: sqs.aws.upbound.io/v1beta1
kind: Queue
metadata:
  name: asya-{namespace}-{actor}
spec:
  forProvider:
    region: us-east-1
    visibilityTimeoutSeconds: 30
    messageRetentionSeconds: 345600  # 4 days
    tags:
      asya.sh/actor: {actor}
      asya.sh/namespace: {namespace}

# 2. KEDA ScaledObject
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: {actor}-scaler
spec:
  scaleTargetRef:
    name: {actor}
  minReplicaCount: {scaling.minReplicas}
  maxReplicaCount: {scaling.maxReplicas}
  pollingInterval: {scaling.pollingInterval}
  cooldownPeriod: {scaling.cooldownPeriod}
  triggers:
    - type: aws-sqs-queue
      metadata:
        queueURL: {queue.status.url}
        queueLength: "5"

# 3. KEDA TriggerAuthentication (for IRSA)
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: {actor}-auth
spec:
  podIdentity:
    provider: aws

# 4. Deployment (if spec.workload provided)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {actor}
  labels:
    asya.sh/actor: {actor}
    asya.sh/inject: "true"
    asya.sh/transport: sqs
    asya.sh/managed-by: crossplane
spec:
  replicas: {workload.replicas}
  selector:
    matchLabels:
      asya.sh/actor: {actor}
  template:
    metadata:
      labels:
        asya.sh/actor: {actor}
        asya.sh/inject: "true"
        asya.sh/transport: sqs
    spec:
      serviceAccountName: asya-actors  # namespace-level SA with IRSA
      containers: {workload.template.spec.containers}

# 5. ServiceAccount (one per namespace, with IRSA annotation)
apiVersion: v1
kind: ServiceAccount
metadata:
  name: asya-actors
  namespace: {namespace}
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/asya-actors-{namespace}
```

#### DLQ Handling

DLQ (Dead Letter Queue) is created **per namespace** when the first actor is created:
- Queue name: `asya-{namespace}-dlq`
- NOT deleted when actors are deleted (preserves failed messages for debugging)
- Managed by separate concern (see error handling flow documentation)

---

### 8. Transport Roadmap

| Priority | Transport | Crossplane Provider | Status |
|----------|-----------|--------------------|---------|
| **P0** | AWS SQS | `provider-aws` (native) | Initial implementation |
| P1 | RabbitMQ | `provider-kubernetes` + RabbitMQ Operator | Future |
| P2 | Google Pub/Sub | `provider-gcp` (native) | Future |
| P2 | Apache Kafka | `provider-kubernetes` + Strimzi Operator | Future |
| P3 | Azure Service Bus | `provider-azure` (native) | Future |
| P3 | NATS Streaming | `provider-kubernetes` + NATS Operator | Future |

---

### 9. Implementation Phases

#### Phase 1: Foundation

1. Install Crossplane in cluster
2. Install required providers (`provider-aws`, `provider-kubernetes`)
3. Define AsyncActor XRD (CompositeResourceDefinition)
4. Create basic SQS Composition (queue + KEDA + deployment)
5. Set up provider credentials (AWS IRSA or access keys)

#### Phase 2: Mutating Webhook

1. Create `asya-injector` Go project with webhook scaffold
2. Implement pod mutation logic (sidecar injection)
3. Add AsyncActor XR querying for configuration
4. Add readiness check (reject pods if infra not ready)
5. Deploy webhook with proper certificates (cert-manager)
6. Test injection with sample workloads

#### Phase 3: Composition Refinement

1. Add IRSA ServiceAccount to Composition
2. Add TriggerAuthentication for KEDA
3. Handle workloadRef case (no Deployment creation)
4. Add proper status patching
5. Test full actor lifecycle (create, scale, delete)

#### Phase 4: Testing & Migration

1. Write E2E tests for Crossplane-based deployment
2. Update Helm charts for new architecture
3. Update documentation
4. Remove old asya-operator code
5. Clean up old CRD definitions

---

### 10. Expected Benefits

| Benefit | Description |
|---------|-------------|
| **Reduced Code** | ~16K LOC operator → ~500 LOC webhook + YAML compositions |
| **Stability** | Battle-tested Crossplane reconciliation (used in production by thousands) |
| **Drift Detection** | Crossplane automatically corrects manual changes to cloud resources |
| **GitOps Friendly** | Webhook doesn't patch existing resources, only mutates at creation |
| **Extensibility** | New transports = new Composition YAML, not new Go code |
| **Separation of Concerns** | Infrastructure (Crossplane) vs Injection (Webhook) clearly separated |

---

### 11. Open Questions

#### Resolved

- **Q: asya-injector or asya-webhook?**
  A: `asya-injector` - more descriptive of what it does

- **Q: Keep `asya.sh/inject` label?**
  A: Yes - follows standard patterns (Istio, Linkerd, Vault), self-documenting

- **Q: How does webhook get AsyncActor config?**
  A: Webhook queries AsyncActor XR directly (single source of truth)

- **Q: Warm-up before scale-to-zero?**
  A: Deferred to future. Initial implementation accepts "Napping" without health verification. See `thoughts-actor-warm-up.md`.

#### Open

- **Q: Composition Functions for status aggregation?**
  Explore whether we need Go-based Composition Functions for replica counts in status, or if basic Ready/NotReady is sufficient initially.

- **Q: Namespace-scoped vs cluster-scoped XRD?**
  Current design is namespace-scoped. Consider if cluster-scoped with namespace field is better for multi-tenancy.

- **Q: Runtime ConfigMap management?**
  Currently operator creates shared ConfigMap. With Crossplane, should each actor have its own, or continue sharing per namespace?

---

### 12. Related Documents

- `thoughts-actor-warm-up.md` - Future exploration of warm-up pattern before scale-to-zero
- `docs/architecture/` - Existing architecture documentation
- `src/asya-operator/` - Current operator implementation (to be replaced)

---

### 13. References

- [Crossplane Documentation](https://docs.crossplane.io/)
- [Crossplane Compositions](https://docs.crossplane.io/latest/concepts/compositions/)
- [Crossplane Composition Functions](https://docs.crossplane.io/latest/concepts/composition-functions/)
- [KEDA SQS Scaler](https://keda.sh/docs/scalers/aws-sqs/)
- [Kubernetes Mutating Admission Webhooks](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/)

---
_Migrated from beads `asya-vab`_
