---
description: "AsyncActor CRD spec: full field reference, compositionSelector, resiliency, transport, state proxy"
---

# AsyncActor CRD

Full field reference for the `AsyncActor` custom resource definition.

**API version**: `asya.sh/v1alpha1`

**Source of truth**: `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml`

---

## Minimal example

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: echo-actor
  namespace: my-project
spec:
  actor: echo-actor
  image: python:3.13-slim
  handler: echo_handler.process
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
```

---

## spec fields

### Required fields

| Field | Type | Description |
|-------|------|-------------|
| `actor` | `string` | Logical actor identity. Determines queue name (`asya-<namespace>-<actor>`). Must be a DNS label: lowercase alphanumeric and hyphens, 1--63 characters, matching `^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`. |
| `image` | `string` | Container image for the runtime container. |
| `handler` | `string` | Python handler path. Formats: `module.function` or `module.Class.method`. Injected as `ASYA_HANDLER` env var. |

### Optional fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `imagePullPolicy` | `string` | `IfNotPresent` | Image pull policy. One of: `Always`, `IfNotPresent`, `Never`. |
| `pythonExecutable` | `string` | `python3` | Python executable path. Override when the image does not have `python3` on PATH (e.g. `/opt/conda/bin/python`). |
| `replicas` | `integer` | `1` | Fixed replica count. Only used when `scaling.enabled` is `false`. Minimum: 1. |
| `env` | `array` | `[]` | Additional environment variables for the runtime container. Each entry has `name` (required), and either `value` or `valueFrom`. |
| `resources` | `object` | -- | Kubernetes resource requests and limits for the runtime container. |
| `tolerations` | `array` | `[]` | Pod tolerations (e.g. for GPU nodes). |
| `nodeSelector` | `object` | -- | Pod node selector (e.g. for GPU nodes). |
| `volumes` | `array` | `[]` | Additional volumes to attach to the pod. |
| `volumeMounts` | `array` | `[]` | Additional volume mounts for the runtime container. |
| `flavors` | `array` | `[]` | List of flavor names (EnvironmentConfigs) to compose. Applied left-to-right; later flavors override earlier ones. Actor inline spec is applied last and always wins. Max 8 items. |
| `secretRefs` | `array` | `[]` | Secret references to inject as env vars. See [secretRefs](#secretrefs). |

---

### scaling

KEDA autoscaling configuration. When enabled, Crossplane creates a KEDA
ScaledObject that scales the actor Deployment based on queue depth.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `boolean` | `true` | Enable KEDA autoscaling. When `false`, the Deployment uses `spec.replicas`. |
| `minReplicaCount` | `integer` | `0` | Minimum replicas. Set to `0` for scale-to-zero. |
| `maxReplicaCount` | `integer` | `10` | Maximum replicas. |
| `pollingInterval` | `integer` | `30` | Seconds between KEDA polling the queue for depth. |
| `cooldownPeriod` | `integer` | `300` | Seconds to wait before scaling down after the queue is empty. |
| `queueLength` | `integer` | `5` | Target queue depth per replica. |
| `advanced` | `object` | -- | Advanced KEDA ScaledObject configuration. See [scaling.advanced](#scalingadvanced). |
| `additionalTriggers` | `array` | `[]` | Extra KEDA trigger objects appended after the primary queue trigger. |

#### scaling.advanced

| Field | Type | Description |
|-------|------|-------------|
| `restoreToOriginalReplicaCount` | `boolean` | Restore to original replica count when ScaledObject is deleted. |
| `formula` | `string` | Composite metric formula for KEDA `scalingModifiers`. Requires `target` to be set. |
| `target` | `string` | Target value for the composite metric formula. Required when `formula` is set. |
| `activationTarget` | `string` | Activation threshold for the composite metric formula. |
| `metricType` | `string` | Metric type: `AverageValue`, `Value`, or `Utilization`. |

---

### resiliency

Retry and error handling configuration. The sidecar uses these settings to
retry failed handler executions before routing to x-sump.

| Field | Type | Description |
|-------|------|-------------|
| `actorTimeout` | `string` | Per-actor processing timeout (Go duration, e.g. `30s`, `5m`). Injected as `ASYA_RESILIENCY_ACTOR_TIMEOUT`. |
| `policies` | `object` | Named retry policies. Key is the policy name. See [resiliency.policies](#resiliencypolicies). |
| `rules` | `array` | Ordered list of error-matching rules. See [resiliency.rules](#resiliencyrules). |

#### resiliency.policies

Each policy is keyed by name (use `"default"` as the fallback policy).

| Field | Type | Description |
|-------|------|-------------|
| `maxAttempts` | `integer` | Maximum attempts (including the first). Minimum: 1. |
| `backoff` | `string` | Backoff strategy: `constant`, `linear`, or `exponential`. |
| `initialDelay` | `string` | Initial retry delay (e.g. `1s`, `500ms`). |
| `maxInterval` | `string` | Maximum retry delay cap (e.g. `300s`, `5m`). |
| `maxDuration` | `string` | Maximum total retry duration before exhaustion (e.g. `10m`). |
| `jitter` | `boolean` | Add randomness to retry delays to prevent thundering herd. |
| `onExhausted` | `array of string` | Actor route to forward the envelope to when the policy is exhausted. When set, the envelope is forwarded instead of being sent to x-sump. |

#### resiliency.rules

Ordered list. The first rule whose `errors` list matches the exception type
(or any ancestor in its MRO) selects the policy. If no rule matches, the
`"default"` policy is used (if defined).

| Field | Type | Description |
|-------|------|-------------|
| `errors` | `array of string` | Error type patterns. FQN patterns (containing `.`) do exact match against `module.qualname`. Short names match the last component. Checked against the full MRO. |
| `policy` | `string` | Name of the policy to apply when this rule matches. |

Example:

```yaml
resiliency:
  actorTimeout: "2m"
  policies:
    default:
      maxAttempts: 3
      backoff: exponential
      initialDelay: "1s"
      maxInterval: "30s"
    rate-limit:
      maxAttempts: 5
      backoff: constant
      initialDelay: "10s"
      onExhausted: ["fallback-actor"]
  rules:
  - errors: ["RateLimitError"]
    policy: rate-limit
  - errors: ["TimeoutError", "ConnectionError"]
    policy: default
```

---

### sidecar

Override default sidecar configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `image.repository` | `string` | `ghcr.io/deliveryhero/asya-sidecar` | Sidecar container image repository. |
| `image.tag` | `string` | Chart.AppVersion | Sidecar image tag. |
| `image.pullPolicy` | `string` | `IfNotPresent` | Image pull policy for the sidecar. |
| `env` | `array` | `[]` | Additional environment variables for the sidecar container. Each entry requires `name` and `value`. |
| `resources` | `object` | -- | Kubernetes resource requests/limits for the sidecar. |

---

### stateProxy

State proxy mount configurations for persistent state access. Each entry adds
a state proxy sidecar container and a logical mount to the pod.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `string` | Unique mount identifier (DNS label, 1--63 chars). |
| `mount.path` | `string` | Absolute path inside the runtime container (must start with `/`). |
| `writeMode` | `string` | Write buffering: `buffered` (default) or `passthrough`. |
| `connector.image` | `string` | Container image for the state proxy connector. |
| `connector.imagePullPolicy` | `string` | Image pull policy (`Always`, `IfNotPresent`, `Never`). Default: `IfNotPresent`. |
| `connector.env` | `array` | Backend-specific environment variables (each: `name`, `value`). |
| `connector.resources` | `object` | Kubernetes resource requests/limits for the connector. |

Example:

```yaml
stateProxy:
- name: checkpoints
  mount:
    path: /state/checkpoints
  writeMode: buffered
  connector:
    image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:latest
    env:
    - name: STATE_BUCKET
      value: my-checkpoints-bucket
```

---

### secretRefs

Inject Kubernetes Secret values as environment variables into the runtime
container.

| Field | Type | Description |
|-------|------|-------------|
| `secretName` | `string` | Name of the Kubernetes Secret (must be in the same namespace). |
| `keys` | `array` | Key-to-env-var mappings. Each entry has `key` (Secret key) and `envVar` (env var name to inject). |

Example:

```yaml
secretRefs:
- secretName: api-credentials
  keys:
  - key: api-key
    envVar: OPENAI_API_KEY
  - key: api-org
    envVar: OPENAI_ORG_ID
```

---

## status fields (read-only)

These fields are set by Crossplane and reflect the current state of the actor.

| Field | Type | Description |
|-------|------|-------------|
| `phase` | `string` | Current phase: `Creating`, `Ready`, or `Napping`. |
| `queueUrl` | `string` | Connection URL for the actor's queue. |
| `queueIdentifier` | `string` | Unique identifier for the queue resource. |
| `infrastructure.queue.ready` | `boolean` | Whether the queue is ready. |
| `infrastructure.queue.message` | `string` | Queue status message. |
| `infrastructure.keda.ready` | `boolean` | Whether the KEDA ScaledObject is ready. |
| `infrastructure.keda.message` | `string` | KEDA status message. |
| `infrastructure.workload.ready` | `boolean` | Whether the Deployment is ready. |
| `infrastructure.workload.replicas` | `integer` | Total desired replicas. |
| `infrastructure.workload.readyReplicas` | `integer` | Number of ready replicas. |

---

## Printer columns

When using `kubectl get asyncactors`, the following columns are displayed:

| Column | Source |
|--------|--------|
| Actor | `spec.actor` |
| Status | `status.phase` |
| Ready | `status.infrastructure.workload.readyReplicas` |
| Replicas | `status.infrastructure.workload.replicas` |
| Queue | `status.queueUrl` (priority 1 -- shown with `-o wide`) |
| Age | `metadata.creationTimestamp` |

---

## Further reading

- [Build Your First Actor](../../usage/start-first-actor.md) -- step-by-step deployment guide
- [Actor Architecture](../components/core-actor.md) -- how Crossplane renders the pod spec
- [Example manifests](https://github.com/deliveryhero/asya/tree/main/examples/asyas) -- real-world AsyncActor configurations
