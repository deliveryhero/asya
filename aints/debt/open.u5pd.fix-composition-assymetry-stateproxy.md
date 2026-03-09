---
title: Fix Composition assymetry for stateProxy
priority: 2 # medium
---

## Problem

The flavor pipeline (`function-asya-flavors`) merges `scaling` and `workload`
from referenced `EnvironmentConfig` flavors and writes the result to the
Crossplane composition context under `asya/resolved-spec`. Downstream Go
template steps read from that context to build Deployments and ScaledObjects.

`stateProxy` is **not** handled by this pipeline. Instead, the `asya-injector`
mutating webhook reads `spec.stateProxy` directly from the live `AsyncActor`
object at Pod admission time — completely bypassing the composition context.

This creates a silent asymmetry: a platform engineer can define a flavor with
`data.stateProxy`, the flavor will merge correctly into `asya/resolved-spec`,
but the resulting context value is **never consumed**. The state proxy sidecar
is never injected.

## Evidence

**`src/function-asya-flavors/fn.go:221-238`** — `extractActorInlineSpec` only
pulls `"scaling"` and `"workload"` from the XR for the final actor-wins
override. `stateProxy` is never extracted or written to the context:

```go
for _, field := range []string{"scaling", "workload"} {
    if v, ok := spec[field]; ok {
        result[field] = v
    }
}
```

**`deploy/helm-charts/asya-crossplane/templates/composition-{sqs,rabbitmq,pubsub}.yaml`** —
all three composition Go templates contain zero references to `stateProxy`
(confirmed: `grep -c stateProxy` returns 0 for each). The templates read
`$resolvedSpec.scaling` and `$resolvedSpec.workload` but nothing else.

**`src/asya-injector/internal/webhook/asyncactor.go:162-210`** — the injector
reads `stateProxy` directly from `unstructured.NestedSlice(spec, "stateProxy")`
where `spec` is `asyncActor.Object["spec"]` — the raw user-written XR spec, not
the composition context:

```go
stateProxies, found, _ := unstructured.NestedSlice(spec, "stateProxy")
```

**`deploy/helm-charts/asya-crew/templates/_helpers.tpl:236`** — the crew chart
explicitly acknowledges the bypass in a comment:

```
Persistence stateProxy spec (inline on AsyncActor, bypasses EnvironmentConfig flavor)
```

This is why `x-sink` and `x-sump` work: the crew chart writes `spec.stateProxy`
**inline** in the AsyncActor manifests (`sink.yaml`, `sump.yaml`). It does not
use the flavor mechanism for this field.

**`deploy/helm-charts/asya-crew/templates/persistence-flavor.yaml`** —
creates an `EnvironmentConfig` with `data.stateProxy` (connector image, bucket
env vars). This data is merged by `function-asya-flavors` into `asya/resolved-spec`
but is never consumed downstream. Effectively dead code for the injection path.

**`examples/asyas/actor-with-persistence-flavor.yaml`** — shows an actor with
`flavors: [asya-persistence-s3]` and no inline `spec.stateProxy`. This example
does not actually work: the state proxy sidecar will not be injected.

## Root cause

Two separate systems handle actor configuration injection:

1. **Crossplane composition pipeline** — runs at XR reconcile time, produces
   Deployments/ScaledObjects, reads from `asya/resolved-spec` context.
2. **Injector webhook** — runs at Pod admission time, reads directly from the
   live `AsyncActor` object, has no access to Crossplane composition context.

The flavor pipeline only feeds system (1). System (2) is unaware of it.

## Fix options

### Option A — Patch `stateProxy` from context back onto the XR spec

After `function-asya-flavors` writes `asya/resolved-spec`, add a composition
step (or extend the function) that patches `stateProxy` from the resolved spec
back onto the XR using `ToCompositeFieldPath`. The injector then reads it as
if the user had written it inline.

- Pro: injector unchanged, clean separation.
- Con: XR spec mutation is unusual; requires a new patch step per composition.

### Option B — Teach the injector to consult the flavor context

Change the injector to also call the Crossplane API or a sidecar to resolve
flavor data at admission time. This is complex and couples admission to the
Crossplane control plane.

- Pro: single source of truth for flavor data.
- Con: adds latency and a hard dependency on Crossplane at admission time.

### Option C — Move stateProxy injection into the composition

Instead of using the injector for `stateProxy`, let the Go template composition
step embed the state proxy sidecar container directly into the Deployment
template by reading `$resolvedSpec.stateProxy`. The injector would no longer
need to handle this field.

- Pro: consistent with how `workload` is already handled.
- Con: compositions become more complex; would require reading from resolved-spec
  for stateProxy and generating sidecar containers and volume mounts in the
  Go template.

### Option D — Drop stateProxy from flavor EnvironmentConfigs (simplify)

Accept that `stateProxy` is always inline and remove `data.stateProxy` from the
persistence `EnvironmentConfig`. Document clearly that flavors configure
`scaling` and `workload` only. Update the `persistence-flavor.yaml` template to
not emit a `stateProxy` key. Update the example actor manifest.

- Pro: removes dead code, clarifies the mental model.
- Con: loses the vision of a fully self-contained platform flavor.

## Recommended fix

**Option C** is the most architecturally consistent with the existing model:
flavors resolve configuration, compositions materialise it into Kubernetes
resources. Extending the Go template to read `stateProxy` from `$resolvedSpec`
and emit the connector container + volume + env keeps the injector focused on
the Asya sidecar (transport) and avoids XR mutation.

**Option D** is the pragmatic short-term fix if full stateProxy flavor support
is not a near-term priority: remove the dead code, update the example, update
the docs. Can be combined with Option C later.

## Affected files

- `src/function-asya-flavors/fn.go` — `extractActorInlineSpec` (Options A, C)
- `deploy/helm-charts/asya-crossplane/templates/composition-{sqs,rabbitmq,pubsub}.yaml` — Go template steps (Option C)
- `deploy/helm-charts/asya-crew/templates/persistence-flavor.yaml` — emits dead `stateProxy` data (Option D)
- `examples/asyas/actor-with-persistence-flavor.yaml` — broken example (Options C, D)
- `docs/tutorials/actor-flavors.md` — corrected in PR #289 to reflect current reality
