# Actor Flavors

Flavors are named, reusable building blocks that platform engineers pre-create
and data scientists (or any actor author) reference by name. A flavor bundles
infrastructure configuration — compute resources, scaling policy,
tolerations — into a single label-addressed unit that gets merged into
an actor's spec at deploy time.

The intent is a clean division of responsibility:

- **Platform engineers** define what "GPU workload", "high-throughput scaler", or
  "S3-persisted actor" means once, in a controlled place.
- **Actor authors** say `flavors: [gpu-standard]` and get the right infrastructure
  without touching Helm charts or cloud-provider details.

---

## The problem flavors solve

Without flavors, every actor needs to repeat the same boilerplate: resource
requests and limits, scaling thresholds, GPU tolerations and node selectors.
When platform requirements change — say, the GPU node pool gets a new taint —
every actor manifest needs updating.

Flavors centralise that boilerplate. The platform team updates one
`EnvironmentConfig`; all actors referencing it pick up the change on the next
reconciliation cycle.

---

## How flavors work

A flavor is a Kubernetes `EnvironmentConfig` (a Crossplane cluster-scoped
resource) with the label `asya.sh/flavor: <name>`. Its `data` field contains a
partial `AsyncActor` spec — only the fields the flavor wants to provide.

When Crossplane reconciles an `AsyncActor` that lists flavors, the
`function-asya-flavors` composition function runs a two-phase resolution:

**Phase 1 — request:** The function reads `spec.flavors` from the actor and tells
Crossplane to fetch the `EnvironmentConfig` resource that matches each flavor
name. Crossplane fetches them and calls the function again with the results.

**Phase 2 — merge:** The function merges all flavor data using type-aware rules,
then applies the actor's inline spec as the final override:

1. Start with an empty spec.
2. For each flavor (in `spec.flavors` order), merge its data using the rules
   described in [Merge semantics](#merge-semantics).
3. Apply the actor's own inline spec fields **last** — the actor always wins
   silently (no error for actor-vs-flavor overlap).

The merged result is written directly to the desired XR's `spec`. Downstream
composition steps (`render-deployment`, `render-scaledobject`) read from that
desired spec — which, after this function runs, reflects the fully resolved
configuration.

### Merge semantics

Merge behavior is determined by Go runtime type dispatch — no per-field
configuration. The rules apply recursively for nested maps:

| Go type | Behavior | Fields |
|---------|----------|--------|
| Lists | Append across flavors | `env`, `tolerations`, `volumes`, `volumeMounts`, `stateProxy`, `secretRefs` |
| Maps/structs | Merge keys recursively; same leaf key in two flavors = error | `nodeSelector`, `scaling`, `resources`, `sidecar`, `resiliency` |
| Scalars | Error if two flavors both set the field | `image`, `handler`, `replicas`, `imagePullPolicy`, `pythonExecutable` |

**Lists are always appended.** Two flavors that both provide `tolerations`
entries get all entries combined. There is no replace or name-merge — the full
lists are concatenated.

**Maps merge recursively.** One flavor can set `resources.limits.cpu` and another
can set `resources.limits.memory` — distinct leaf keys at any nesting depth are
merged. Only the same leaf key in two flavors triggers an error.

**Scalars conflict.** If two flavors both set `image`, the merge fails with an
error naming both flavors. Use a single flavor for scalar fields, or let the
actor's inline spec override.

**Type mismatches are errors.** If one flavor defines a field as a list and
another defines it as a scalar, the merge fails.

**Conflict errors include flavor names and full key path:**
```
flavor merge conflict: flavors "gpu-a100" and "high-throughput" conflict on scaling.minReplicaCount
```

### What fields flavors can provide

| Field | Type | Merge behavior |
|-------|------|----------------|
| `image` | scalar | error if two flavors set it |
| `handler` | scalar | error if two flavors set it |
| `imagePullPolicy` | scalar | error if two flavors set it |
| `pythonExecutable` | scalar | error if two flavors set it |
| `replicas` | scalar | error if two flavors set it |
| `resources` | map | merge keys recursively |
| `env` | list | append across flavors |
| `tolerations` | list | append across flavors |
| `nodeSelector` | map | merge keys; same key = error |
| `volumes` | list | append across flavors |
| `volumeMounts` | list | append across flavors |
| `scaling` | map | merge keys recursively |
| `resiliency` | map | merge keys recursively |
| `sidecar` | map | merge keys recursively |
| `stateProxy` | list | append across flavors |
| `secretRefs` | list | append across flavors |

Infrastructure fields (`actor`, `transport`, `flavors`) are excluded from the
merge — they cannot be set by flavors.

---

## Creating a flavor (platform engineer)

A flavor is a plain `EnvironmentConfig` manifest. The only required convention is
the `asya.sh/flavor: <name>` label and a `data` field shaped like a partial
`AsyncActor` spec.

### Example: compute profile for GPU inference

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: gpu-standard
  labels:
    asya.sh/flavor: gpu-standard
data:
  scaling:
    minReplicaCount: 1
    maxReplicaCount: 4
    queueLength: 1
  resources:
    requests:
      cpu: 2
      memory: 8Gi
      nvidia.com/gpu: "1"
    limits:
      nvidia.com/gpu: "1"
  tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
  nodeSelector:
    accelerator: nvidia-t4
```

### Example: spot instance tolerations

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
```

Combining `gpu-standard` and `spot-tolerant` on the same actor appends both
tolerations — the pod tolerates both GPU taints and spot instance taints.

### Example: S3 persistence flavor

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
        value: my-checkpoints-bucket
      - name: AWS_REGION
        value: eu-west-1
```

Multiple state flavors compose: `s3-checkpoints` + `redis-cache` would append
both `stateProxy` entries.

---

## Using flavors (actor author)

Add `spec.flavors` to an `AsyncActor`. The list is ordered: flavors are applied
left-to-right. Any inline spec fields you write in the actor manifest override
flavor values silently.

### Example: GPU inference actor

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: embedding-service
  namespace: ml-platform
spec:
  actor: embedding-service
  transport: sqs
  flavors: [gpu-standard]

  image: my-org/embedding-service:latest
  handler: embeddings.handler
  env:
  - name: MODEL_NAME
    value: text-embedding-ada-002
```

The actor defines its image and handler. The `gpu-standard` flavor provides
resources, tolerations, node selectors, and scaling — none of which the actor
author needs to know about.

### Example: combining composable flavors

Flavors compose when they contribute to different fields or different keys
within the same field:

```yaml
spec:
  flavors: [gpu-standard, spot-tolerant, s3-checkpoints]

  image: my-org/batch-inference:latest
  handler: inference.handle
```

- `gpu-standard` provides resources, scaling, GPU tolerations, and node selector
- `spot-tolerant` appends a spot toleration (lists append)
- `s3-checkpoints` appends a stateProxy entry (lists append)

No conflicts — each flavor contributes to different fields or appends to lists.

### Example: overriding a flavor value

A flavor provides defaults; the actor can always override them inline:

```yaml
spec:
  flavors: [gpu-standard]

  # Override just the scaling — everything else comes from the flavor
  scaling:
    maxReplicaCount: 2
```

The `gpu-standard` flavor might set `maxReplicaCount: 4`. Writing
`scaling: {maxReplicaCount: 2}` in the actor's inline spec replaces the entire
`scaling` field from the flavor. The actor always wins.

---

## What causes a conflict

Two flavors conflict when they both set the same leaf key. Examples:

```yaml
# flavor-a                         # flavor-b
data:                               data:
  scaling:                            scaling:
    minReplicaCount: 1                  minReplicaCount: 5
```

This errors: `flavors "flavor-a" and "flavor-b" conflict on scaling.minReplicaCount`.

To fix: consolidate the conflicting field into a single flavor, or have the
actor set it inline (actor always wins over all flavors).

**Not a conflict** — distinct leaf keys merge:
```yaml
# flavor-a                         # flavor-b
data:                               data:
  resources:                          resources:
    limits:                             limits:
      cpu: "500m"                         memory: "4Gi"
```

This merges: `resources.limits` gets both `cpu` and `memory`.

---

## Constraints

- Maximum 8 flavors per actor.
- Flavor names must be at least 3 characters.
- Flavors are cluster-scoped resources. The same `EnvironmentConfig` is shared
  across all namespaces — a single platform-level flavor serves all tenants.
- If a referenced flavor does not exist (no matching `EnvironmentConfig` with
  the correct label), Crossplane will keep the actor in a `Waiting` state and
  log `Waiting for flavor EnvironmentConfigs`. The actor will not be deployed
  until all listed flavors are available.

---

## Debugging

Check the `AsyncActor` status conditions to see whether flavor resolution
succeeded:

```bash
kubectl describe asyncactor <name> -n <namespace>
```

Look for a condition message from the `resolve-flavors` step. If flavors are
missing, it shows `Waiting for N flavor EnvironmentConfigs`. If flavors
conflict, the `Synced` condition will be `False` with an error message naming
the conflicting flavors and key path.

Verify the `EnvironmentConfig` exists and carries the correct label:

```bash
kubectl get environmentconfigs -l asya.sh/flavor=<name>
```

To inspect what the resolved spec looks like after merging, check the
Crossplane function logs:

```bash
kubectl logs -n crossplane-system \
  -l pkg.crossplane.io/revision \
  --all-containers=true | grep "Flavors applied"
```
