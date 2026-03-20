# Creating and Managing Actor Flavors

This guide covers actor flavors from the platform engineer's perspective — how to create, configure, and manage reusable infrastructure presets for actors.

## Overview

Flavors are named, reusable configuration bundles backed by Crossplane `EnvironmentConfig` resources. Platform engineers define what "GPU workload", "high-throughput scaler", or "S3-persisted actor" means once, in a controlled place. Actor authors reference them by name and get the right infrastructure without touching cloud-provider details.

This guide assumes you are a **platform engineer** responsible for defining flavors. For how actor authors use flavors, see [usage/guide-actor-flavors.md](../usage/guide-actor-flavors.md).

## How Flavors Work

A flavor is a cluster-scoped `EnvironmentConfig` resource with two requirements:

1. Resource name matching the flavor name (the function fetches by name)
2. A `data` field shaped like a partial AsyncActor spec

By convention, flavors also carry the label `asya.sh/flavor: <name>` for discoverability (`kubectl get environmentconfigs -l asya.sh/flavor`).

When Crossplane reconciles an AsyncActor that lists flavors, the `function-asya-flavors` composition function:

1. Reads `spec.flavors` from the actor
2. Requests each `EnvironmentConfig` by name from Crossplane
3. Merges all flavor data using type-aware rules
4. Applies the actor's inline spec as the final override
5. Writes the resolved spec back onto the XR's desired state

Downstream composition steps (`render-deployment`, `render-scaledobject`) read from the resolved spec.

## Creating a Flavor

### Minimal Example

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: cpu-standard
  labels:
    asya.sh/flavor: cpu-standard
data:
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: "1"
      memory: 1Gi
```

**Apply**:

```bash
kubectl apply -f cpu-standard.yaml
```

**Result**: Any AsyncActor with `flavors: [cpu-standard]` inherits the resource limits.

### Anatomy of a Flavor

| Field | Description |
|-------|-------------|
| `metadata.name` | Flavor name — actors reference this name in `spec.flavors` (the function fetches by resource name) |
| `metadata.labels["asya.sh/flavor"]` | Convention label for discoverability (`kubectl get environmentconfigs -l asya.sh/flavor`) |
| `data` | Partial AsyncActor spec — only the fields this flavor provides |

**Naming convention**: The `metadata.name` is the canonical flavor identifier. Keep the `asya.sh/flavor` label value in sync with the resource name for discoverability.

## Flavor Composability

Flavors are designed to compose. An actor can use multiple flavors simultaneously (e.g., `gpu-a100` + `checkpoint-state` + `spot-tolerant`).

### Merge Semantics

| Go type | Behavior | Example fields |
|---------|----------|----------------|
| Lists | Append across flavors | `env`, `tolerations`, `volumes`, `volumeMounts`, `stateProxy`, `secretRefs` |
| Maps/structs | Merge keys recursively; same leaf key = error | `nodeSelector`, `scaling`, `resources`, `sidecar`, `resiliency` |
| Scalars | Error if two flavors both set the field | `image`, `handler`, `replicas`, `imagePullPolicy`, `pythonExecutable` |

**Key principle**: Distinct leaf keys at any nesting depth are merged. Only same leaf key overlap triggers an error.

### Example: Composing Tolerations

Two flavors that both provide `tolerations` entries get all entries combined:

```yaml
# gpu-tolerations flavor
data:
  tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
```

```yaml
# spot-tolerations flavor
data:
  tolerations:
  - key: cloud.google.com/gke-spot
    operator: Equal
    value: "true"
    effect: NoSchedule
```

**Actor**:

```yaml
spec:
  flavors: [gpu-tolerations, spot-tolerations]
```

**Result**: Pod has both tolerations.

### Example: Composing Resources

Two flavors with distinct resource keys merge:

```yaml
# cpu-flavor
data:
  resources:
    limits:
      cpu: "2"
```

```yaml
# memory-flavor
data:
  resources:
    limits:
      memory: 4Gi
```

**Actor**:

```yaml
spec:
  flavors: [cpu-flavor, memory-flavor]
```

**Result**: Pod has both CPU and memory limits.

### Example: Conflict

Two flavors with the same leaf key error:

```yaml
# flavor-a
data:
  scaling:
    minReplicaCount: 1
```

```yaml
# flavor-b
data:
  scaling:
    minReplicaCount: 5
```

**Actor**:

```yaml
spec:
  flavors: [flavor-a, flavor-b]
```

**Result**: Error at reconciliation time:

```
flavor merge conflict: flavors "flavor-a" and "flavor-b" conflict on scaling.minReplicaCount
```

**Fix**: Consolidate the conflicting field into a single flavor, or have the actor set it inline (actor always wins).

## Common Flavor Patterns

### GPU Compute Profile

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: gpu-a100
  labels:
    asya.sh/flavor: gpu-a100
data:
  scaling:
    minReplicaCount: 1
    maxReplicaCount: 4
    queueLength: 1  # Process one message at a time on GPU
  resources:
    requests:
      cpu: 4
      memory: 16Gi
      nvidia.com/gpu: "1"
    limits:
      nvidia.com/gpu: "1"
  tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
  nodeSelector:
    accelerator: nvidia-a100
```

**Use case**: Actors that require A100 GPUs for inference.

### High-Throughput Scaling

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: high-throughput
  labels:
    asya.sh/flavor: high-throughput
data:
  scaling:
    minReplicaCount: 5
    maxReplicaCount: 50
    queueLength: 10
    pollingInterval: 10  # Scale up faster
    cooldownPeriod: 60   # Scale down faster
```

**Use case**: Actors with high message volume and fast processing time.

### S3 Checkpoints

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: s3-checkpoints
  labels:
    asya.sh/flavor: s3-checkpoints
data:
  stateProxy:
  - name: checkpoints
    mount:
      path: /state/checkpoints
    connector:
      image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
      env:
      - name: STATE_BUCKET
        value: ml-checkpoints
      - name: AWS_REGION
        value: us-west-2
      resources:
        requests:
          cpu: 50m
          memory: 128Mi
```

**Use case**: Actors that persist checkpoints to S3.

### Spot Instance Tolerations

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: spot-tolerant
  labels:
    asya.sh/flavor: spot-tolerant
data:
  tolerations:
  - key: cloud.google.com/gke-spot
    operator: Equal
    value: "true"
    effect: NoSchedule
  - key: kubernetes.azure.com/scalesetpriority
    operator: Equal
    value: spot
    effect: NoSchedule
```

**Use case**: Actors that can run on spot/preemptible nodes.

### Secrets Injection

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: openai-secrets
  labels:
    asya.sh/flavor: openai-secrets
data:
  secretRefs:
  - secretName: openai-creds
    keys:
    - key: api-key
      envVar: OPENAI_API_KEY
```

**Use case**: Actors that need OpenAI API credentials.

### Retry Policies

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: aggressive-retries
  labels:
    asya.sh/flavor: aggressive-retries
data:
  resiliency:
    actorTimeout: 10m
    policies:
      transient:
        maxAttempts: 5
        backoff: exponential
        initialDelay: 1s
        maxInterval: 30s
    rules:
    - errors: ["TimeoutError", "ConnectionError"]
      policy: transient
```

**Use case**: Actors that call flaky external APIs.

## Flavor Lifecycle

### Creating a Flavor

```bash
kubectl apply -f flavor.yaml
```

**Availability**: Flavor is immediately available to all namespaces (cluster-scoped resource).

### Updating a Flavor

Edit the `EnvironmentConfig` and re-apply:

```bash
kubectl edit environmentconfig gpu-a100
# or
kubectl apply -f gpu-a100-v2.yaml
```

**Effect**: Crossplane reconciles all AsyncActor resources referencing this flavor. The new configuration is applied on the next reconciliation cycle.

**Rollout**: Changes propagate gradually as Crossplane re-reconciles actors. Force immediate reconciliation:

```bash
kubectl annotate asyncactor my-actor crossplane.io/paused=false --overwrite
```

### Deprecating a Flavor

1. Mark the flavor as deprecated (convention: add a label or annotation):

```yaml
metadata:
  labels:
    asya.sh/flavor: gpu-t4
    asya.sh/deprecated: "true"
  annotations:
    asya.sh/deprecation-message: "Use gpu-a100 instead"
```

2. Communicate the deprecation to users.

3. Monitor usage:

```bash
kubectl get asyncactors --all-namespaces -o yaml | grep "gpu-t4"
```

4. Once no actors reference the flavor, delete it:

```bash
kubectl delete environmentconfig gpu-t4
```

### Migrating to a New Flavor

**Scenario**: Replace `gpu-t4` with `gpu-a100`.

**Strategy**:

1. Create `gpu-a100` flavor with the new configuration.
2. Update actors incrementally:

```yaml
spec:
  flavors: [gpu-a100]  # Was [gpu-t4]
```

3. Once all actors migrated, delete `gpu-t4`.

**Tip**: Use a temporary combined flavor during migration:

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: gpu-migration
  labels:
    asya.sh/flavor: gpu-migration
data:
  # Combine fields from both gpu-t4 and gpu-a100
  # Allows actors to switch from [gpu-t4] to [gpu-migration] to [gpu-a100]
```

## Fields Flavors Can Provide

Flavors can set any non-infrastructure spec field:

| Field | Type | Description |
|-------|------|-------------|
| `image` | scalar | Container image (conflicts if two flavors set it) |
| `handler` | scalar | Handler path (conflicts if two flavors set it) |
| `imagePullPolicy` | scalar | Always, IfNotPresent, Never |
| `pythonExecutable` | scalar | Python binary path |
| `replicas` | scalar | Fixed replica count (when scaling disabled) |
| `resources` | map | CPU, memory, GPU requests/limits |
| `env` | list | Environment variables |
| `tolerations` | list | Pod tolerations |
| `nodeSelector` | map | Node selector labels |
| `volumes` | list | Pod volumes |
| `volumeMounts` | list | Runtime container volume mounts |
| `scaling` | map | KEDA autoscaling configuration |
| `resiliency` | map | Retry policies and actor timeout |
| `sidecar` | map | Sidecar overrides |
| `stateProxy` | list | State proxy mounts |
| `secretRefs` | list | Secret references |

**Infrastructure fields** (`actor`, `transport`, `flavors`) are excluded from the merge — they cannot be set by flavors.

## Constraints

- **Maximum 8 flavors per actor**: Enforced by XRD `maxItems: 8`.
- **Minimum flavor name length**: 3 characters (enforced by XRD).
- **Cluster-scoped only**: `EnvironmentConfig` is a cluster-scoped resource. Namespace-scoped flavors are not yet supported (planned in aint `jgwn`).
- **Missing flavor**: If a referenced flavor does not exist, the actor remains in `Waiting` state until the flavor is created.

## Debugging Flavors

### Check if a Flavor Exists

```bash
kubectl get environmentconfigs -l asya.sh/flavor=gpu-a100
```

Expected output:

```
NAME       AGE
gpu-a100   5d
```

### List All Flavors

```bash
kubectl get environmentconfigs -l asya.sh/flavor
```

### Inspect Flavor Data

```bash
kubectl get environmentconfig gpu-a100 -o yaml
```

### Check Actor Status

If an actor references a missing or conflicting flavor, check the status:

```bash
kubectl describe asyncactor my-actor -n prod
```

Look for conditions from the `resolve-flavors` step:

- **Missing flavor**: `Waiting for N flavor EnvironmentConfigs`
- **Conflict**: `Synced: False`, message naming the conflicting flavors and key path

### Force Re-Reconciliation

After updating a flavor, force Crossplane to re-reconcile an actor:

```bash
kubectl annotate asyncactor my-actor crossplane.io/paused=false --overwrite -n prod
```

### View Composition Logs

Check the `function-asya-flavors` logs to see the resolved spec:

```bash
kubectl logs -n crossplane-system \
  -l pkg.crossplane.io/revision \
  --all-containers=true | grep "Flavors applied"
```

## Best Practices

1. **Use composable flavors** — define small, focused flavors (e.g., `gpu-a100`, `spot-tolerant`, `s3-checkpoints`) that actors combine, rather than monolithic flavors that duplicate configuration.

2. **Avoid scalar conflicts** — do not set scalar fields (like `image` or `handler`) in flavors unless the flavor is meant to be exclusive. Use flavors for infrastructure, not application code.

3. **Document flavors** — add annotations with usage instructions:

```yaml
metadata:
  annotations:
    asya.sh/description: "A100 GPU compute profile with 16Gi memory"
    asya.sh/example: "flavors: [gpu-a100]"
```

4. **Version flavors explicitly** — if making breaking changes, create a new flavor (`gpu-a100-v2`) rather than updating the existing one in-place.

5. **Monitor flavor usage** — track which actors reference which flavors to understand impact before deprecating:

```bash
kubectl get asyncactors --all-namespaces -o json | \
  jq -r '.items[] | select(.spec.flavors != null) | "\(.metadata.namespace)/\(.metadata.name): \(.spec.flavors)"'
```

6. **Use namespace-aware prefixes for state** — when defining `stateProxy` flavors, use `STATE_PREFIX=$(NAMESPACE)/` to isolate state across namespaces.

7. **Test flavor changes in staging** — validate flavor updates on a test actor before rolling out to production.

## Example: Building a Flavor Library

**Step 1**: Create base compute profiles:

```bash
kubectl apply -f - <<EOF
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: cpu-small
  labels:
    asya.sh/flavor: cpu-small
data:
  resources:
    requests:
      cpu: 250m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi
---
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: cpu-large
  labels:
    asya.sh/flavor: cpu-large
data:
  resources:
    requests:
      cpu: "2"
      memory: 4Gi
    limits:
      cpu: "4"
      memory: 8Gi
---
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: gpu-a100
  labels:
    asya.sh/flavor: gpu-a100
data:
  resources:
    requests:
      cpu: 4
      memory: 16Gi
      nvidia.com/gpu: "1"
    limits:
      nvidia.com/gpu: "1"
  tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
  nodeSelector:
    accelerator: nvidia-a100
EOF
```

**Step 2**: Create scaling profiles:

```bash
kubectl apply -f - <<EOF
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: scale-minimal
  labels:
    asya.sh/flavor: scale-minimal
data:
  scaling:
    minReplicaCount: 0
    maxReplicaCount: 3
    queueLength: 5
---
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: scale-aggressive
  labels:
    asya.sh/flavor: scale-aggressive
data:
  scaling:
    minReplicaCount: 10
    maxReplicaCount: 100
    queueLength: 10
    pollingInterval: 10
    cooldownPeriod: 60
EOF
```

**Step 3**: Create persistence flavors:

```bash
kubectl apply -f - <<EOF
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: s3-checkpoints
  labels:
    asya.sh/flavor: s3-checkpoints
data:
  stateProxy:
  - name: checkpoints
    mount:
      path: /state/checkpoints
    connector:
      image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
      env:
      - name: STATE_BUCKET
        value: ml-checkpoints
      - name: AWS_REGION
        value: us-west-2
---
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: redis-cache
  labels:
    asya.sh/flavor: redis-cache
data:
  stateProxy:
  - name: cache
    mount:
      path: /state/cache
    connector:
      image: ghcr.io/deliveryhero/asya-state-proxy-redis-buffered-cas:v1.0.0
      env:
      - name: REDIS_URL
        value: redis://redis.default.svc.cluster.local:6379/0
EOF
```

**Step 4**: Actors compose flavors:

```yaml
# Small CPU actor with minimal scaling
spec:
  flavors: [cpu-small, scale-minimal]

# GPU actor with aggressive scaling and S3 checkpoints
spec:
  flavors: [gpu-a100, scale-aggressive, s3-checkpoints]

# Large CPU actor with Redis cache
spec:
  flavors: [cpu-large, scale-minimal, redis-cache]
```

## Security Considerations

1. **Cluster-scoped resources**: `EnvironmentConfig` is cluster-scoped. Any user who can create AsyncActors can reference any flavor. Use RBAC to control who can create or modify flavors.

2. **Secret injection**: Flavors that reference secrets (via `secretRefs`) give actors access to those secrets. Ensure flavors only reference secrets that actors in any namespace should access.

3. **IAM roles**: Flavors that configure `stateProxy` with S3 backends rely on IRSA. Ensure the IAM role grants appropriate permissions for all actors that might use the flavor.

4. **Node selectors and tolerations**: Flavors that set `nodeSelector` or `tolerations` control where pods are scheduled. Ensure the target nodes are available and appropriately secured.

---

**Using flavors**: To choose and use flavors in your actor specs, see [usage/guide-actor-flavors.md](../usage/guide-actor-flavors.md).
