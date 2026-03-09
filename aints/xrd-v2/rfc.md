# RFC: Flatten AsyncActor XRD, remove leaked provider fields

Status: draft

## Problem

The current `XAsyncActor` XRD mixes three concerns in `spec`:

1. **User-facing actor configuration** — what DS/ML engineers care about
   (image, handler, scaling, resources, state)
2. **Provider wiring** — AWS/GCP infrastructure details that leaked into the
   user-facing API (`region`, `gcpProject`, `providerConfigRef`, `irsa`)
3. **Kubernetes deployment internals** — deeply nested container spec
   (`workload.template.spec.containers[]`) that forces array merge logic

This creates three problems:
- Users must understand provider-specific fields to deploy a simple actor
- The `containers[]` array requires a custom Go merge function for flavors
- Transport-specific fields (`region` for SQS, `gcpProject` for Pub/Sub)
  pollute a supposedly transport-agnostic actor spec

## Leaked fields audit

| Field | Why it's wrong | Where it belongs |
|---|---|---|
| `region` | AWS-specific, only used by SQS composition | Helm values → composition template (already has default) |
| `gcpProject` | GCP-specific, only used by Pub/Sub composition | Helm values → composition template (already has default) |
| `providerConfigRef` | Crossplane internal wiring | Helm values → composition template (already has default) |
| `irsa` | AWS-specific IAM concern | Helm values → composition template, or EnvironmentConfig |

All four fields already have defaults from Helm values. The per-actor override
was a premature escape hatch — no user has ever needed to deploy actors in the
same namespace with different AWS regions or different ProviderConfigs.

If a team needs a different region or provider config, they deploy a separate
Crossplane composition (separate Helm release with different values), not a
per-actor override.

## Proposed v1alpha2 spec

### Minimal actor (3 fields)

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  image: my-image:latest
  handler: my_module.process
  transport: sqs
```

### Full spec

```yaml
spec:
  # --- Required ---
  actor: my-actor                          # queue naming, routing identity
  transport: sqs                           # enum: sqs | rabbitmq | pubsub
  image: my-image:latest                   # runtime container image

  # --- Code (removed by workloadRef) ---
  handler: my_module.process               # ASYA_HANDLER value
  env:                                     # runtime container env vars
    - name: MODEL_NAME
      value: gpt-4
  resources:                               # runtime container resources
    limits:
      nvidia.com/gpu: "1"
    requests:
      memory: 4Gi

  # --- Scheduling (removed by workloadRef) ---
  tolerations:                             # pod-level tolerations
    - key: nvidia.com/gpu
      operator: Exists
      effect: NoSchedule
  nodeSelector:                            # pod-level node selector
    gpu-type: a100

  # --- Scaling (KEDA — always present) ---
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    pollingInterval: 30
    cooldownPeriod: 300
    queueLength: 5

  # --- State (always present) ---
  stateProxy:
    - name: memory
      mount: {path: /state/memory}
      writeMode: buffered
      connector:
        image: ghcr.io/deliveryhero/asya-state-proxy-s3:latest

  # --- Error handling (always present) ---
  resiliency:
    retry:
      maxAttempts: 3
      policy: exponential

  # --- Secrets (always present) ---
  secretRefs:
    - secretName: api-keys
      keys:
        - key: openai-key
          envVar: OPENAI_API_KEY

  # --- Flavors (always present) ---
  flavors: [gpu-a100, high-throughput]

  # --- Power-user (rarely needed) ---
  replicas: 1                              # only when scaling.enabled=false
  sidecar:                                 # sidecar image/resource overrides
    image: ghcr.io/deliveryhero/asya-sidecar:latest
  volumes: [...]                           # custom pod volumes
  volumeMounts: [...]                      # custom runtime container mounts

  # --- Future ---
  # workloadRef:
  #   name: my-existing-deployment         # bring your own Deployment
```

### Removed fields

| Removed | Replacement |
|---|---|
| `region` | Helm value `awsProviderConfig.region` baked into composition |
| `gcpProject` | Helm value `gcpProviderConfig.projectId` baked into composition |
| `providerConfigRef` | Helm value `awsProviderConfig.name` baked into composition |
| `irsa` | Helm value or EnvironmentConfig (cluster-wide policy) |
| `workload.kind` | Always `Deployment` (only supported kind) |
| `workload.template.spec.containers[]` | Flattened to `image`, `env`, `resources`, `volumeMounts` |
| `workload.template.spec.tolerations` | Promoted to `spec.tolerations` |
| `workload.template.spec.nodeSelector` | Promoted to `spec.nodeSelector` |
| `workload.template.spec.volumes` | Promoted to `spec.volumes` |
| `workload.replicas` | Promoted to `spec.replicas` |

### New field: `handler`

Currently `ASYA_HANDLER` is set as an env var inside the container spec. With
the flat XRD, it becomes a first-class field. The composition's
render-deployment step injects it as `ASYA_HANDLER` env var on the runtime
container.

This is cleaner: `handler: my_module.process` instead of:
```yaml
workload:
  template:
    spec:
      containers:
        - name: asya-runtime
          env:
            - name: ASYA_HANDLER
              value: my_module.process
```

## Impact on flavors

With flat XRD and non-intersecting flavors, `function-asya-flavors` reduces
from ~200 LOC to ~30 LOC:

```go
merged := map[string]interface{}{}
for _, flavor := range flavorData {
    for k, v := range flavor {
        merged[k] = v  // last flavor wins (non-intersecting = no conflict)
    }
}
for k, v := range actorSpec {
    merged[k] = v  // actor always wins
}
dxr.Resource.Object["spec"] = merged
```

No `DeepMerge`, no `mergeByName`, no field allow/deny lists.

Env vars do NOT belong in flavors — secrets are namespace-scoped and can't
be referenced from cluster-scoped EnvironmentConfigs.

## Impact on workloadRef

The flat structure makes workloadRef transition clean. Fields are categorized:

**Survive workloadRef** (Asya's job regardless of who owns the Deployment):
- `actor`, `transport`, `flavors`
- `scaling`, `resiliency`
- `stateProxy`, `secretRefs`

**Removed by workloadRef** (the user's Deployment owns these):
- `image`, `handler`, `env`, `resources`
- `tolerations`, `nodeSelector`, `volumes`, `volumeMounts`
- `replicas`, `sidecar`

With flat fields, deprecation is per-field with clear validation:
"cannot set `image` when `workloadRef` is specified."

## Impact on compositions

Each composition (SQS, Pub/Sub, RabbitMQ) needs updates:

1. **render-deployment**: read `$xr.spec.image`, `$xr.spec.resources`,
   `$xr.spec.tolerations`, etc. instead of
   `$xr.spec.workload.template.spec.containers[0]`
2. **render-queue**: region/gcpProject/providerConfigRef come from Helm
   values (composition template), not from `$xr.spec`
3. **render-serviceaccount**: IRSA config from Helm values or
   EnvironmentConfig, not from `$xr.spec.irsa`

## Impact on injector

The injector reads the AsyncActor spec to configure sidecar injection. It
currently looks at `spec.workload.template.spec.containers` to find the
runtime container. With flat XRD, it reads `spec.image` directly.

## Migration

v1alpha1 → v1alpha2 with Crossplane's version conversion (webhook). Or
parallel support: serve both versions, convert internally. Given that
Asya is pre-1.0, a clean break with migration docs is also acceptable.

## Open questions

1. Should `handler` be a required field or can it remain an env var in `env[]`?
2. Should `volumes`/`volumeMounts` be a single `mounts` field instead?
3. Should `sidecar` be exposed at all, or fully internal?
4. Timeline: do this before or after v1alpha1 stabilizes?
