# function-asya-flavors

Crossplane composition function that resolves and merges actor flavor
EnvironmentConfigs into a unified spec on the XR.

For full documentation on how flavors work, merge semantics, and
EnvironmentConfig syntax, see [docs/internal/actor-flavors.md](../../docs/internal/actor-flavors.md).

## What it does

1. Reads `spec.flavors[]` from the observed XR (a list of flavor names).
2. Requests each flavor's `EnvironmentConfig` by label `asya.sh/flavor=<name>`
   via the Crossplane Requirements API.
3. Merges all flavor data using type-aware rules:
   - Lists (e.g. `tolerations`, `stateProxy`): appended across flavors
   - Maps/structs (e.g. `nodeSelector`, `scaling`): keys merged recursively, same leaf key = error
   - Scalars (e.g. `replicas`): only one flavor may set the field
4. Applies the actor's inline spec as the final override (actor always wins).
5. Writes the resolved spec back onto the XR's desired state.

Downstream pipeline steps (render-deployment, render-scaledobject) read
from `$xr.spec.*` and see the fully resolved configuration.

## Where it fits

```
Crossplane Composition Pipeline
================================

  1. function-asya-flavors    <-- this function
     - resolves EnvironmentConfigs
     - merges flavors + actor inline spec
     - writes resolved spec to desired XR

  2. render-deployment         (function-go-templating)
     - reads $xr.spec.workload, $xr.spec.sidecar, etc.

  3. render-scaledobject       (function-go-templating)
     - reads $xr.spec.scaling

  4. auto-ready                (function-auto-ready)
```

## Why this exists

Two capabilities are missing from stock Crossplane functions:

1. **Dynamic resource fetching by variable-length list.** The actor's
   `spec.flavors` is a variable-length array. For each name, the function
   must fetch a matching EnvironmentConfig. Only a custom function using
   the Requirements API can do this — `function-go-templating` has no
   access to it, and `function-environment-configs` requires a fixed
   number of selectors defined at composition-write time.

2. **Type-aware merge with conflict detection.** When multiple flavors
   contribute to the same field, merge behavior depends on the field's
   Go runtime type (list=append, map=merge keys, scalar=error). Stock
   functions either replace arrays entirely or have no conflict detection.

## When this function becomes unnecessary

If Crossplane adds type-aware merge support to
`function-environment-configs` (e.g., list append + map merge-by-key +
scalar conflict detection), the architecture simplifies to:

```
Crossplane Composition Pipeline (future)
=========================================

  1. function-environment-configs  (with type-aware merge)
     - fetches EnvironmentConfigs by selector
     - merges with type-aware rules
     - writes to composition context or XR

  2. render-deployment             (function-go-templating)
  3. render-scaledobject           (function-go-templating)
  4. auto-ready                    (function-auto-ready)
```

No custom Go code needed. The custom function can be dropped entirely.
This capability is not currently on the Crossplane roadmap.

## Development

```bash
go test ./... -v     # run tests
go build ./...       # build
```
