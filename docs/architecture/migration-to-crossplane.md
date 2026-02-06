# AsyncActor Syntax: Operator vs Crossplane

This document covers the AsyncActor CRD syntax changes when migrating from asya-operator to asya-crossplane.

## API Surface

Both systems use the same API group, version, kind, and short names:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
```

| Property | asya-operator | asya-crossplane |
|----------|---------------|-----------------|
| API Group | `asya.sh` | `asya.sh` |
| Version | `v1alpha1` | `v1alpha1` |
| Kind | `AsyncActor` | `AsyncActor` (Claim) / `XAsyncActor` (Composite) |
| Short names | `asya`, `asyas` | `asya`, `asyas` |
| Scope | Namespaced | Namespaced (Claim) |
| CRD type | Native `CustomResourceDefinition` | Crossplane `CompositeResourceDefinition` |

Users interact with `AsyncActor` Claims which have the same UX as native CRDs.

## Spec Field Comparison

### `transport` (required)

| Aspect | asya-operator | asya-crossplane |
|--------|---------------|-----------------|
| Type | Free-form string (`minLength: 1`) | Enum: `sqs`, `rabbitmq` |
| Default | None | `sqs` |
| Validation | Non-empty, must match operator config | Enum-restricted at admission |

**Before** (operator):
```yaml
spec:
  transport: rabbitmq  # Any operator-configured transport name
```

**After** (crossplane):
```yaml
spec:
  transport: rabbitmq  # Must be "sqs" or "rabbitmq"
```

### Actor Naming

The mechanism for overriding the logical actor name is unchanged - both systems use the `asya.sh/actor` label.

| Aspect | asya-operator | asya-crossplane |
|--------|---------------|-----------------|
| Mechanism | `asya.sh/actor` label | `asya.sh/actor` label |
| Default | `metadata.name` | `metadata.name` |
| Queue format | `asya-{namespace}-{actorName}` | `asya-{namespace}-{actorName}` |

**Both** (operator and crossplane):
```yaml
metadata:
  name: text-processor-eu
  labels:
    asya.sh/actor: text-processor   # Override actor name via label
```

No migration needed for actor naming.

### `scaling`

| Field | asya-operator default | asya-crossplane default | Notes |
|-------|----------------------|------------------------|-------|
| `enabled` | `false` | `true` | Crossplane enables scaling by default |
| `minReplicas` | `0` | `0` | Unchanged |
| `maxReplicas` | `50` | `10` | Crossplane uses a lower default |
| `pollingInterval` | `10` | `30` | Crossplane polls less frequently |
| `cooldownPeriod` | `60` | `300` | Crossplane waits longer before scaling down |
| `queueLength` | `5` | `5` | Unchanged |
| `advanced` | Supported | Removed | See below |

**`scaling.advanced` removed**: The `advanced` sub-object (`formula`, `target`, `activationTarget`, `metricType`, `restoreToOriginalReplicaCount`) is not available in Crossplane. If you relied on custom scaling formulas, these must be configured directly on the KEDA ScaledObject.

**Before** (operator):
```yaml
spec:
  scaling:
    enabled: true           # Must opt-in explicitly
    minReplicas: 0
    maxReplicas: 50          # Default: 50
    pollingInterval: 10      # Default: 10
    cooldownPeriod: 60       # Default: 60
    queueLength: 10
    advanced:
      formula: "ceil(queueLength / 10)"
      target: "10"
      activationTarget: "5"
      metricType: "AverageValue"
```

**After** (crossplane):
```yaml
spec:
  scaling:
    enabled: true            # Default: true (opt-out instead of opt-in)
    minReplicas: 0
    maxReplicas: 50          # Must override default of 10
    pollingInterval: 10      # Must override default of 30
    cooldownPeriod: 60       # Must override default of 300
    queueLength: 10
    # advanced: not available
```

### `timeout` (removed)

The `timeout` section (`processing`, `gracefulShutdown`) is not present in the Crossplane XRD. Timeout behavior is handled by the sidecar injector configuration.

**Before** (operator):
```yaml
spec:
  timeout:
    processing: 600
    gracefulShutdown: 60
```

**After** (crossplane): Field removed from spec. No equivalent field.

### `sidecar`

| Field | asya-operator | asya-crossplane | Notes |
|-------|---------------|-----------------|-------|
| `image` | Supported | Supported | Same |
| `imagePullPolicy` | Supported (enum) | Removed | |
| `resources` | Supported | Supported | Same |
| `env` | Supported (full EnvVar) | Removed | |

Sidecar injection is handled by the `asya-injector` webhook (separate component) rather than the operator.

**Before** (operator):
```yaml
spec:
  sidecar:
    image: ghcr.io/deliveryhero/asya-sidecar:v2.1.0
    imagePullPolicy: Always
    resources:
      limits:
        cpu: 1000m
        memory: 512Mi
      requests:
        cpu: 200m
        memory: 128Mi
    env:
    - name: ASYA_LOG_LEVEL
      value: debug
    - name: ENABLE_TRACING
      value: "true"
```

**After** (crossplane):
```yaml
spec:
  sidecar:
    image: ghcr.io/deliveryhero/asya-sidecar:v2.1.0
    resources:
      limits:
        cpu: 1000m
        memory: 512Mi
      requests:
        cpu: 200m
        memory: 128Mi
    # imagePullPolicy and env: not available in spec
```

### `workload`

| Field | asya-operator | asya-crossplane | Notes |
|-------|---------------|-----------------|-------|
| `kind` | `Deployment` / `StatefulSet` | `Deployment` / `StatefulSet` | Same |
| `replicas` | Supported (default: `1`) | Supported (default: `1`) | Same |
| `template` | Required | Required | Same structure |
| `pythonExecutable` | Supported (default: `python3`) | Removed | |

The `template` contents (PodTemplateSpec) remain the same - you still define your `asya-runtime` container with handler env vars, resources, volumes, etc.

**Before** (operator):
```yaml
spec:
  workload:
    kind: Deployment
    replicas: 1
    pythonExecutable: python3    # Custom Python path
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-runtime:latest
          env:
          - name: ASYA_HANDLER
            value: "processor.process"
```

**After** (crossplane):
```yaml
spec:
  workload:
    kind: Deployment
    replicas: 1
    # pythonExecutable: not available
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-runtime:latest
          env:
          - name: ASYA_HANDLER
            value: "processor.process"
```

### `workloadRef` (new)

Crossplane introduces `workloadRef` as an alternative to `workload`. They are mutually exclusive (CEL-validated).

With `workloadRef`, you manage the Deployment externally (via GitOps, Helm, or manual kubectl) and Crossplane only creates the queue and KEDA resources. The external Deployment must have labels `asya.sh/actor` and `asya.sh/inject: "true"` for sidecar injection.

**Before** (operator): Not supported. Operator always creates the Deployment.

**After** (crossplane):
```yaml
spec:
  transport: sqs
  workloadRef:
    name: my-existing-deployment
    kind: Deployment
  scaling:
    enabled: true
    maxReplicas: 10
```

### New Fields in Crossplane

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `region` | string | `us-east-1` | AWS region for SQS queue |
| `providerConfigRef` | string | `default` | Name of AWS ProviderConfig |
| `irsa.enabled` | boolean | `true` | Create ServiceAccount with IRSA |
| `irsa.roleArn` | string | auto-generated | Custom IAM role ARN |

### Fields Removed in Crossplane

| Field | Former Default | Notes |
|-------|----------------|-------|
| `timeout.processing` | `300` | Removed from spec |
| `timeout.gracefulShutdown` | `30` | Removed from spec |
| `sidecar.imagePullPolicy` | `IfNotPresent` | Removed from spec |
| `sidecar.env` | `[]` | Removed from spec |
| `workload.pythonExecutable` | `python3` | Removed from spec |
| `scaling.advanced.*` | (various) | Entire sub-object removed |

## Status Field Comparison

The status structure is redesigned.

**Before** (operator):
```yaml
status:
  status: Running              # Running, Napping, Degraded, Creating, ...
  replicas: 3                  # Ready replicas
  desiredReplicas: 5           # Target replicas
  totalReplicas: 5             # Total non-terminated pods
  readyReplicas: 3             # Ready pods
  pendingReplicas: 2           # Not-yet-ready pods
  failingPods: 0               # CrashLoopBackOff, ImagePullBackOff
  readyReplicasSummary: "3/5"  # Formatted summary
  scalingMode: KEDA            # KEDA or Manual
  lastScaleTime: "..."         # Timestamp
  lastScaleDirection: up       # up, down, ""
  lastScaleFormatted: "5m ago (up)"
  transportStatus: Ready       # Ready or NotReady
  queuedMessages: 42           # Messages in queue
  processingMessages: 5        # In-flight messages
  workloadRef:                 # Reference to Deployment
    apiVersion: apps/v1
    kind: Deployment
    name: text-processor
    namespace: default
  scaledObjectRef:             # Reference to ScaledObject
    name: text-processor
    namespace: default
  conditions:                  # TransportReady, WorkloadReady, ScalingReady
    - type: WorkloadReady
      status: "True"
```

**After** (crossplane):
```yaml
status:
  phase: Ready                 # Creating, Ready, Napping
  queueUrl: "https://..."     # SQS queue URL
  queueArn: "arn:aws:..."     # SQS queue ARN
  infrastructure:
    queue:
      ready: true
      message: "Queue is ready"
    keda:
      ready: true
      message: "ScaledObject is ready"
    workload:
      ready: true
      replicas: 5
      readyReplicas: 3
```

## Printer Columns Comparison

**Before** (`kubectl get asyas` with operator):
```
NAME             ACTOR            STATUS    RUNNING  FAILING  TOTAL  DESIRED  MIN  MAX  LAST-SCALE     AGE
text-processor   text-processor   Running   3        0        3      3        0    50   5m ago (up)    1h
```

**After** (`kubectl get asyas` with crossplane):
```
NAME             STATUS   READY  REPLICAS  TRANSPORT  AGE
text-processor   Ready    3      3         sqs        1h
```

Extended output (`kubectl get asyas -o wide`) adds the `Queue` column with the SQS URL.

## Validation Changes

| Rule | asya-operator | asya-crossplane |
|------|---------------|-----------------|
| `asya-runtime` container required | Go webhook validation | CEL validation in XRD |
| `command` not allowed on `asya-runtime` | Go webhook validation | CEL validation in XRD |
| `workload` required | Schema-level (`required`) | Not required (can use `workloadRef`) |
| `workload` / `workloadRef` mutual exclusion | N/A | CEL: `!has(self.workload) \|\| !has(self.workloadRef)` |
| `scaling.queueLength >= 1` | Schema-level (`minimum: 1`) | Not enforced in schema |
| `scaling.maxReplicas >= 1` | Schema-level (`minimum: 1`) | Not enforced in schema |
| Reserved volume names/paths | Go webhook validation | Webhook (asya-injector) |
| Reserved container names | Go webhook validation | Webhook (asya-injector) |

## Side-by-Side Examples

### Minimal Actor

**Before** (operator):
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello-actor
  namespace: default
spec:
  transport: rabbitmq
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
          env:
          - name: ASYA_HANDLER
            value: "echo_handler.process"
          resources:
            limits:
              cpu: 1000m
              memory: 512Mi
            requests:
              cpu: 100m
              memory: 128Mi
```

**After** (crossplane):
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello-actor
  namespace: default
spec:
  transport: rabbitmq
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
          env:
          - name: ASYA_HANDLER
            value: "echo_handler.process"
          resources:
            limits:
              cpu: 1000m
              memory: 512Mi
            requests:
              cpu: 100m
              memory: 128Mi
```

Minimal actors are identical. The main behavioral difference: Crossplane enables KEDA scaling by default (`scaling.enabled: true`, 0-10 replicas), while the operator kept scaling disabled by default.

### Fully Configured Actor

**Before** (operator):
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor-eu
  namespace: production
  labels:
    asya.sh/actor: text-processor
    asya.sh/flow: document-processing
    region: eu-central-1
spec:
  transport: sqs

  timeout:
    processing: 600
    gracefulShutdown: 60

  sidecar:
    image: ghcr.io/deliveryhero/asya-sidecar:v2.1.0
    imagePullPolicy: Always
    resources:
      requests:
        cpu: 200m
        memory: 128Mi
      limits:
        cpu: 1000m
        memory: 512Mi
    env:
    - name: ASYA_LOG_LEVEL
      value: debug

  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 20
    pollingInterval: 10
    cooldownPeriod: 60
    queueLength: 10
    advanced:
      formula: "ceil(queueLength / 10)"
      target: "10"
      activationTarget: "5"
      metricType: "AverageValue"

  workload:
    kind: Deployment
    replicas: 1
    pythonExecutable: python3
    template:
      metadata:
        labels:
          region: eu-central-1
      spec:
        nodeSelector:
          topology.kubernetes.io/region: eu-central-1
        containers:
        - name: asya-runtime
          image: my-registry/text-processor:v1.0.0
          env:
          - name: ASYA_HANDLER
            value: text_processor.process
          - name: REGION
            value: eu-central-1
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: 2000m
              memory: 4Gi
```

**After** (crossplane):
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor-eu
  namespace: production
  labels:
    asya.sh/actor: text-processor
    asya.sh/flow: document-processing
    region: eu-central-1
spec:
  transport: sqs
  region: eu-central-1
  providerConfigRef: default

  # timeout: removed from spec

  sidecar:
    image: ghcr.io/deliveryhero/asya-sidecar:v2.1.0
    resources:
      requests:
        cpu: 200m
        memory: 128Mi
      limits:
        cpu: 1000m
        memory: 512Mi
    # imagePullPolicy, env: removed from spec

  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 20
    pollingInterval: 10
    cooldownPeriod: 60
    queueLength: 10
    # advanced: removed

  irsa:
    enabled: true
    roleArn: "arn:aws:iam::123456789:role/text-processor"

  workload:
    kind: Deployment
    replicas: 1
    # pythonExecutable: removed
    template:
      metadata:
        labels:
          region: eu-central-1
      spec:
        nodeSelector:
          topology.kubernetes.io/region: eu-central-1
        containers:
        - name: asya-runtime
          image: my-registry/text-processor:v1.0.0
          env:
          - name: ASYA_HANDLER
            value: text_processor.process
          - name: REGION
            value: eu-central-1
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: 2000m
              memory: 4Gi
```

### External Workload (Crossplane only)

This pattern is only available with Crossplane. The user manages the Deployment externally, and Crossplane only provisions the queue and KEDA resources:

```yaml
# User-managed Deployment (via Argo CD, Flux, or kubectl)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: text-processor
  namespace: production
  labels:
    asya.sh/actor: text-processor
    asya.sh/inject: "true"          # Triggers sidecar injection
spec:
  replicas: 1
  selector:
    matchLabels:
      asya.sh/actor: text-processor
  template:
    metadata:
      labels:
        asya.sh/actor: text-processor
        asya.sh/inject: "true"
    spec:
      containers:
      - name: asya-runtime
        image: my-registry/text-processor:v1.0.0
        env:
        - name: ASYA_HANDLER
          value: text_processor.process
---
# AsyncActor Claim (queue + KEDA only)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor
  namespace: production
spec:
  transport: sqs
  workloadRef:
    name: text-processor
    kind: Deployment
  scaling:
    enabled: true
    maxReplicas: 10
```
