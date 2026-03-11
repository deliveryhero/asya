# Actor Flavors

Flavors are named, reusable building blocks that platform engineers pre-create
and data scientists (or any actor author) reference by name. A flavor bundles
infrastructure configuration — compute resources, scaling policy,
environment variables — into a single label-addressed unit that gets merged into
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

**Phase 2 — merge:** The function applies the flavor data sequentially:

1. Start with an empty spec.
2. Apply `flavors[0]`.
3. Apply `flavors[1]` on top — later flavors override conflicting scalar values
   from earlier ones.
4. Continue for each remaining flavor.
5. Apply the actor's own inline spec fields (`spec.image`, `spec.handler`,
   `spec.resources`, `spec.scaling`, etc.) **last** — the actor always wins.

The merged result is written directly to the desired XR's `spec`. Downstream
composition steps (`render-deployment`, `render-scaledobject`) read from that
desired spec — which, after this function runs, reflects the fully resolved
configuration.

[smp]: https://kubernetes.io/docs/tasks/manage-kubernetes-objects/update-api-object-kubectl-patch/#use-a-strategic-merge-patch-to-update-a-deployment

### Merge semantics for lists

The flavor merge uses a name-keyed deep merge for list fields. Arrays whose
items all carry a `name` string key are merged by that key (same name = later
flavor wins; different names accumulate). Arrays without a `name` key replace
the previous value entirely.

| Field | Behavior |
|---|---|
| `env` | Merged by `name` — add or override individual variables |
| `volumes` | Merged by `name` — add or override individual volumes |
| `volumeMounts` | Merged by `name` — add or override individual mounts |
| `tolerations` | Replaced — toleration items have no `name` key |
| `nodeSelector` | Merged (map, keys replace) |

A flavor that adds `env: [{name: MODEL_PATH, value: /models/v2}]` **merges**
that variable into the runtime container's existing env list. It does not
replace the entire list.

Scalar fields (`image`, `handler`, `resources`, `replicas`, etc.) follow
last-write-wins: the last flavor to set a value wins, and the actor's inline
spec overrides all.

### What fields flavors can provide

| Field | Effect |
|---|---|
| `image` | Container image for the asya-runtime container |
| `handler` | Python handler path (module.function or module.Class.method) |
| `imagePullPolicy` | Image pull policy |
| `pythonExecutable` | Python executable override |
| `resources` | Resource requests and limits for the runtime container |
| `env` | Additional environment variables (merged by name) |
| `tolerations` | Pod tolerations (replaced) |
| `nodeSelector` | Node selector (merged) |
| `volumes` | Extra pod volumes (merged by name) |
| `volumeMounts` | Extra volume mounts for the runtime container (merged by name) |
| `scaling` | KEDA ScaledObject parameters (minReplicaCount, maxReplicaCount, etc.) |
| `resiliency` | Retry policy and actor timeout |

`stateProxy` is **not** resolved through the flavor pipeline. The composition
reads `spec.stateProxy` directly from the live `AsyncActor` object, not from
the flavor-merged desired spec — so flavor-provided `stateProxy` data is never
picked up. Write `spec.stateProxy` inline in the actor manifest, or let a Helm
chart generate it (as `asya-crew` does for `x-sink` and `x-sump`).

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
    queueLength: 1          # one job per GPU instance at a time
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

### Example: high-throughput scaler profile

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: high-throughput
  labels:
    asya.sh/flavor: high-throughput
data:
  scaling:
    minReplicaCount: 2
    maxReplicaCount: 50
    pollingInterval: 10
    cooldownPeriod: 60
    queueLength: 2
```

### Example: S3 persistence flavor (managed by asya-crew)

The `asya-crew` chart creates a persistence `EnvironmentConfig` when
`persistence.enabled: true` is set. Because `stateProxy` is not propagated
through the flavor pipeline (see above), this `EnvironmentConfig` currently
carries bucket and connector metadata as a reference — but you still need to
write `spec.stateProxy` inline in your actor to activate the sidecar injection.

```yaml
# In asya-crew Helm values (platform engineer):
persistence:
  enabled: true
  backend: s3
  config:
    bucket: my-checkpoints-bucket
    region: eu-west-1
```

Actor manifest with inline stateProxy (actor author):

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: data-processor
  namespace: my-project
spec:
  actor: data-processor
  transport: sqs
  image: my-org/data-processor:latest
  handler: processor.handle

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

  env:
  - name: ASYA_PERSISTENCE_MOUNT
    value: /state/checkpoints/data-processor
```

---

## Using flavors (actor author)

Add `spec.flavors` to an `AsyncActor`. The list is ordered: flavors are applied
left-to-right, and any inline spec fields you write in the actor manifest
(`spec.image`, `spec.handler`, `spec.scaling`, etc.) override flavor values.

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

### Example: combining multiple flavors

Flavors compose. An actor can reference several flavors to layer their
configurations:

```yaml
spec:
  flavors: [gpu-standard, high-throughput]

  image: my-org/batch-inference:latest
  handler: inference.handle
```

`gpu-standard` applies first, setting GPU resources and tolerations.
`high-throughput` applies second, overriding scaling parameters. The actor's
inline fields (image, handler) apply last.

### Example: overriding a flavor value

A flavor provides defaults; the actor can always override them inline:

```yaml
spec:
  flavors: [gpu-standard]

  # Override just the replica count — everything else comes from the flavor
  scaling:
    maxReplicaCount: 2
```

The `gpu-standard` flavor might set `maxReplicaCount: 4`. Writing `maxReplicaCount: 2`
in the actor's `spec.scaling` overrides that specific field while leaving all
other flavor-provided values (tolerations, resources, etc.) intact.

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
missing, it shows `Waiting for N flavor EnvironmentConfigs`. Verify the
`EnvironmentConfig` exists and carries the correct label:

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
