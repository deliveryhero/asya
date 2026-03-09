# Actor Flavors

Flavors are named, reusable building blocks that platform engineers pre-create
and data scientists (or any actor author) reference by name. A flavor bundles
infrastructure configuration — compute resources, scaling policy, persistence,
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
requests and limits, scaling thresholds, sidecar configuration for state
persistence. When platform requirements change — say, the GPU node pool gets a
new taint — every actor manifest needs updating.

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

**Phase 2 — merge:** The function applies the flavor data sequentially as
[strategic merge patches][smp]:

1. Start with an empty spec.
2. Apply `flavors[0]`.
3. Apply `flavors[1]` on top — later flavors override conflicting scalar values
   from earlier ones.
4. Continue for each remaining flavor.
5. Apply the actor's own inline `spec.scaling` and `spec.workload` **last** —
   the actor always wins.

The merged result is stored in the Crossplane pipeline context under the key
`asya/resolved-spec`. Downstream composition steps (the Go templates that
produce Deployments, ScaledObjects, etc.) read from that key instead of the raw
actor spec.

[smp]: https://kubernetes.io/docs/tasks/manage-kubernetes-objects/update-api-object-kubectl-patch/#use-a-strategic-merge-patch-to-update-a-deployment

### Merge semantics for lists

Flavors use Kubernetes strategic merge patch, not a plain deep merge. This means
list fields follow Kubernetes merge-key conventions:

| Field | Merged by |
|---|---|
| `workload.template.spec.containers` | `name` |
| `workload.template.spec.containers[*].env` | `name` |
| `workload.template.spec.volumes` | `name` |
| `workload.template.spec.initContainers` | `name` |
| `workload.template.spec.tolerations` | `key` |

A flavor that adds `env: [{name: MODEL_PATH, value: /models/v2}]` to the
`asya-runtime` container **merges** that variable into the container's existing
env list. It does not replace the entire list. The same applies to tolerations
and volumes.

Scalar fields (`minReplicas`, `maxReplicas`, `cpu`, etc.) follow last-write-wins:
the last flavor to set a value wins, and the actor's inline spec overrides all.

### What fields flavors can provide

| Section | Effect |
|---|---|
| `scaling` | KEDA ScaledObject parameters (minReplicas, maxReplicas, pollingInterval, cooldownPeriod, queueLength) |
| `workload` | Deployment template: containers, resources, env vars, volumes, tolerations, node selectors |
| `stateProxy` | State proxy sidecar configuration for persistence connectors |

Note: `stateProxy` can only come from a flavor, not from the actor's inline spec.
This is intentional — storage infrastructure is a platform concern.

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
    minReplicas: 1
    maxReplicas: 4
    queueLength: 1          # one job per GPU instance at a time
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
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
    minReplicas: 2
    maxReplicas: 50
    pollingInterval: 10
    cooldownPeriod: 60
    queueLength: 2
```

### Example: S3 persistence (managed by asya-crew)

The `asya-crew` chart can create a persistence flavor automatically when
`persistence.enabled: true` is set. Platform engineers configure the crew chart;
the resulting `EnvironmentConfig` wires up the `asya-state-proxy` sidecar and
exposes the bucket mount to actors.

```yaml
# In asya-crew Helm values:
persistence:
  enabled: true
  backend: s3
  config:
    bucket: my-checkpoints-bucket
    region: eu-west-1
```

This creates an `EnvironmentConfig` named `asya-persistence-s3` (by default)
that injects the state proxy connector as a sidecar. Actor authors reference it
by name; they never touch the connector image or bucket configuration.

---

## Using flavors (actor author)

Add `spec.flavors` to an `AsyncActor`. The list is ordered: flavors are applied
left-to-right, and any inline `spec.scaling` or `spec.workload` you write in
the actor manifest overrides flavor values.

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

  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-org/embedding-service:latest
          env:
          - name: ASYA_HANDLER
            value: embeddings.handler
          - name: MODEL_NAME
            value: text-embedding-ada-002
```

The actor defines its image and handler. The `gpu-standard` flavor provides
resources, tolerations, node selectors, and scaling — none of which the actor
author needs to know about.

### Example: combining multiple flavors

Flavors compose. An actor can reference a scaling profile and a persistence
flavor together:

```yaml
spec:
  flavors: [high-throughput, asya-persistence-s3]

  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-org/data-processor:latest
          env:
          - name: ASYA_HANDLER
            value: processor.handle
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints/data-processor
```

`high-throughput` applies first, setting scaling parameters. `asya-persistence-s3`
applies second, adding the state proxy sidecar. The actor's inline env vars
(including `ASYA_PERSISTENCE_MOUNT`) apply last and are not affected by either
flavor.

### Example: overriding a flavor value

A flavor provides defaults; the actor can always override them inline:

```yaml
spec:
  flavors: [gpu-standard]

  # Override just the replica count — everything else comes from the flavor
  scaling:
    maxReplicas: 2
```

The `gpu-standard` flavor might set `maxReplicas: 4`. Writing `maxReplicas: 2`
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
