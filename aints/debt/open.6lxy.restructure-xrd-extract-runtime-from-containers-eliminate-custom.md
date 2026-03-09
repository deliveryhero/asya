---
title: "Restructure XRD: extract runtime from containers[], eliminate custom merge function"
priority: 2 # medium
dependencies:
  - u5pd
---

## Summary

Restructure the AsyncActor XRD to extract the runtime container spec from the deeply nested `workload.template.spec.containers[]` array into a flat `spec.runtime` field. Rename `workload` to `deploymentSpec` for pod-level concerns. This eliminates the containers array merge-by-name problem entirely.

## Motivation

The current `function-asya-flavors` custom Go function exists primarily because Crossplane cannot merge arrays by key (containers by name, env vars by name). By restructuring the XRD to avoid arrays that need key-based merging, we can replace the custom function with Crossplane's built-in `function-patch-and-transform` using `mergeOptions: {keepMapValues: true}`.

## Proposed XRD structure

```yaml
spec:
  runtime:             # extracted from containers[{name: asya-runtime}]
    image: my-image
    resources: {}
    volumeMounts: []
  deploymentSpec:      # pod-level (ex workload.template.spec)
    tolerations: []
    nodeSelector: {}
    volumes: []
  scaling: {}
  resiliency: {}
  sidecar: {}
  stateProxy: []
```

## Design constraints

- Flavors are non-intersecting by design (each flavor owns a distinct concern)
- Env vars do NOT belong in flavors (secrets are namespace-scoped)
- Actor inline spec always wins over flavor values (keepMapValues: true)
- Must preserve workloadRef path for future bring-your-own-deployment support
- Must preserve custom volume/secret mounting into workload

## Spike task

Before committing to the restructuring, validate that `function-patch-and-transform` with `FromEnvironmentFieldPath` + `mergeOptions: {keepMapValues: true}` works correctly at the field level (data.scaling → spec.scaling, etc.).

## Scope

- XRD schema change (breaking)
- All 3 compositions rewritten (render-deployment reads runtime + deploymentSpec)
- Injector updates (reads container spec)
- All test manifests and examples updated
- Migration guide for existing AsyncActors
- Remove function-asya-flavors custom Go code entirely

## Depends on

- u5pd (ship current simplified merge as v0, then this replaces it)
