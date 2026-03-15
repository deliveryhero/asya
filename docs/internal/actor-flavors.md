# Actor Flavors

Flavors are reusable configuration bundles backed by Crossplane
`EnvironmentConfig` resources. They let platform teams define common actor
presets (GPU resources, secrets, persistence, scaling profiles) that data
science teams reference by name.

## How it works

```
AsyncActor (XR)             EnvironmentConfig
spec:                       metadata:
  flavors:                    labels:
    - gpu-t4       -------->    asya.sh/flavor: gpu-t4
    - persistence  -------->    asya.sh/flavor: persistence
  image: ...                data:
  handler: ...                scaling: { minReplicaCount: 1 }
  resources: ...              resources: { limits: { nvidia.com/gpu: "1" } }
```

1. `function-asya-flavors` reads `spec.flavors` from the XR.
2. For each flavor name, it requests the matching `EnvironmentConfig` via
   label `asya.sh/flavor=<name>` using Crossplane's Requirements API.
3. Crossplane fetches them and provides them on the next reconciliation.
4. The function merges all flavor data in order using type-aware rules
   (see [Merge semantics](#merge-semantics) below).
5. The actor's inline spec is applied last (actor always wins).
6. The resolved spec is written back onto the XR's desired state.
7. Downstream composition steps read from `$xr.spec.*`.

## Merge semantics

Flavors are composable — an actor can use multiple flavors simultaneously
(e.g., `gpu-a100` + `checkpoint-state` + `inference-cache`). Overlap behavior
is determined by Go runtime type dispatch, not per-field configuration:

| Go type | Behavior | Fields |
|---------|----------|--------|
| `[]interface{}` (lists) | Append across flavors | `stateProxy`, `tolerations`, `secretRefs`, `volumes`, `volumeMounts`, `env` |
| `map[string]interface{}` (maps/structs) | Merge keys recursively; same leaf key in two flavors = error | `nodeSelector`, `scaling`, `resources`, `sidecar`, `resiliency` |
| Scalars | Error if two flavors both set the field | `replicas`, `image`, `handler`, `imagePullPolicy`, `pythonExecutable` |

**Conflict errors include flavor names and the full key path** for debuggability:
```
flavor merge conflict: flavors "gpu-a100" and "high-throughput" conflict on scaling.minReplicaCount
```

**Map/struct fields are merged recursively**: one flavor can set
`resources.limits.cpu` and another can set `resources.limits.memory` —
distinct leaf keys at any nesting depth are merged. Only same leaf key
overlap triggers an error. This enables natural composition patterns like
splitting CPU and GPU resource flavors.

**Actor inline spec always wins** over flavor values, silently. This is
intentional — the actor is the most specific override (like CSS inline styles
over class rules).

### Examples

Two state flavors, no conflict (lists append):
```yaml
# gpu-a100 flavor                # inference-cache flavor
data:                             data:
  stateProxy:                       stateProxy:
  - name: checkpoints               - name: cache
    mount: {path: /checkpoints}       mount: {path: /cache}
# Result: stateProxy has both entries
```

Two flavors with distinct scaling keys, no conflict (map merge):
```yaml
# base-scaling flavor            # high-throughput flavor
data:                             data:
  scaling:                          scaling:
    minReplicaCount: 1                maxReplicaCount: 50
# Result: scaling has both keys
```

Two flavors with same scaling key (error):
```yaml
# flavor-a                       # flavor-b
data:                             data:
  scaling:                          scaling:
    minReplicaCount: 1                minReplicaCount: 5
# Error: flavors "flavor-a" and "flavor-b" conflict on scaling.minReplicaCount
```

## EnvironmentConfig syntax

Flavor data uses the same schema as the XRD spec. No custom DSL:

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
  scaling:
    minReplicaCount: 1
    maxReplicaCount: 5
```

## Actor-wins override

The actor's inline spec always takes precedence. If a flavor sets
`scaling.minReplicaCount: 1` and the actor sets `scaling.minReplicaCount: 3`,
the actor's value wins. No error is raised for actor-vs-flavor overlap.

Infrastructure fields (`actor`, `transport`, `flavors`) are excluded from the merge.

## Supported fields

Flavors can set any non-infrastructure spec field:
- `scaling` - KEDA autoscaling configuration
- `resources` - Runtime container resource requests/limits
- `env` - Runtime container environment variables
- `tolerations` - Pod tolerations
- `nodeSelector` - Pod node selector
- `volumes` - Pod volumes
- `volumeMounts` - Runtime container volume mounts
- `stateProxy` - State proxy sidecar mounts
- `resiliency` - Retry policies
- `sidecar` - Sidecar overrides
- `secretRefs` - Secret references

## Limitations

- **Cluster-scoped only**: EnvironmentConfigs are cluster-scoped Crossplane
  resources. Namespace-scoped flavors via ConfigMaps are planned (see aint
  `jgwn`).
- **Max 8 flavors per actor**: Enforced by XRD `maxItems: 8`.

## Architecture decision

See `ADR: Custom composition function for actor flavors` in the aint archive
for why a custom Crossplane function is needed instead of stock functions.
The two missing capabilities in Crossplane:
1. Dynamic resource fetching by variable-length list (Requirements API)
2. Type-aware merge with conflict detection across EnvironmentConfigs
