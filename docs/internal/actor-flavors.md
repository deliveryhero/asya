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
  workload: ...             data:
                              scaling: { minReplicas: 1 }
                              workload: { template: ... }
```

1. `function-asya-flavors` reads `spec.flavors` from the XR.
2. For each flavor name, it requests the matching `EnvironmentConfig` via
   label `asya.sh/flavor=<name>` using Crossplane's Requirements API.
3. Crossplane fetches them and provides them on the next reconciliation.
4. The function deep-merges all flavor data in order (left-to-right, later
   flavors override earlier ones).
5. The actor's inline spec is applied last (actor always wins).
6. The resolved spec is written back onto the XR's desired state.
7. Downstream composition steps read from `$xr.spec.*`.

## Merge semantics

| Field type | Behavior | Example |
|-----------|----------|---------|
| Scalars | Last writer wins | `scaling.minReplicas: 2` overrides `1` |
| Dicts/objects | Deep merge | `scaling.maxReplicas` added alongside `minReplicas` |
| Arrays of name-keyed objects | Merge by `name` | Env vars accumulate; same name = last wins |
| Other arrays | Replace | Tolerations, volumes replace entirely |

**Name-keyed arrays** are detected automatically: if all items in both base
and patch arrays are objects with a `"name"` string key, they merge by name.
This covers `containers[].env`, `sidecar.env`, and `stateProxy[].connector.env`.

**Non-name-keyed arrays** (e.g. `tolerations`, `volumes`) replace atomically.
If you need tolerations from multiple sources, combine them in a single flavor.

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
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: OPENAI_API_KEY
            valueFrom:
              secretKeyRef:
                name: openai-creds
                key: api-key
  scaling:
    minReplicas: 1
    maxReplicas: 5
```

## Actor-wins override

The actor's inline spec always takes precedence. If a flavor sets
`scaling.minReplicas: 1` and the actor sets `scaling.minReplicas: 3`,
the actor's value wins.

Infrastructure fields (`actor`, `transport`, `flavors`, `region`,
`gcpProject`, `providerConfigRef`, `irsa`) are excluded from the merge.

## Supported fields

Flavors can set any non-infrastructure spec field:
- `scaling` - KEDA autoscaling configuration
- `workload` - Pod template, containers, env vars, resources
- `stateProxy` - State proxy sidecar mounts
- `resiliency` - Retry policies
- `sidecar` - Sidecar overrides
- `secretRefs` - Secret references

## Limitations

- **Cluster-scoped only**: EnvironmentConfigs are cluster-scoped Crossplane
  resources. Namespace-scoped flavors via ConfigMaps are planned (see aint
  `jgwn`).
- **Max 8 flavors per actor**: Enforced by XRD `maxItems: 8`.
- **No cross-flavor array merge for non-name-keyed arrays**: Use a single
  flavor to bundle all tolerations, volumes, etc.

## Architecture decision

See `ADR: Custom composition function for actor flavors` in the aint archive
for why a custom Crossplane function is needed instead of stock functions.
The two missing capabilities in Crossplane:
1. Dynamic resource fetching by variable-length list (Requirements API)
2. Array merge by key across EnvironmentConfigs (name-keyed merge)
