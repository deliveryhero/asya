---
title: "Restructure XRD: flatten spec, simplify flavor merge to ~30 LOC"
priority: 2 # medium
dependencies:
  - u5pd
---

## Summary

Flatten the AsyncActor XRD: extract runtime container fields from
`workload.template.spec.containers[]` to root-level `spec.image`,
`spec.resources`, etc. Move pod-level fields (`tolerations`, `nodeSelector`,
`volumes`) to root. This eliminates the containers array and the merge-by-name
problem, reducing `function-asya-flavors` from ~200 LOC to ~30 LOC.

## Motivation

The custom Go merge function exists because Crossplane cannot merge arrays by
key. Flattening the XRD removes all array-merge needs. With non-intersecting
flavors (each flavor owns distinct root-level keys), the merge becomes trivial
flat map assignment.

NOTE: The custom function is NOT fully eliminable. Dynamic flavor selection
(reading `spec.flavors[]` and fetching N EnvironmentConfigs via the Requirements
API) has no built-in Crossplane equivalent. And `function-patch-and-transform`
`mergeOptions.keepMapValues` is shallow (not deep-merge), so it cannot replace
even the simplified merge logic.

## Proposed flat XRD

```yaml
spec:
  # Identity
  actor: echo
  transport: sqs
  flavors: [gpu-a100]

  # Code (goes away with workloadRef)
  image: my-image:latest
  handler: my_module.process
  env: [...]
  resources: {limits: {"nvidia.com/gpu": "1"}}

  # Scaling (KEDA)
  scaling: {minReplicas: 0, maxReplicas: 10}

  # Scheduling (goes away with workloadRef)
  tolerations: [...]
  nodeSelector: {}

  # State
  stateProxy: [...]

  # Error handling
  resiliency: {retry: {maxAttempts: 3}}

  # Secrets
  secretRefs: [...]

  # Power-user
  sidecar: {image: ..., resources: ...}
  volumes: [...]
  volumeMounts: [...]

  # Future
  workloadRef: {name: my-deployment}
```

## What this achieves

- function-asya-flavors: ~200 LOC to ~30 LOC (flat map merge, no mergeByName)
- No `containers[]` array — the root cause of merge complexity
- Non-intersecting flavors: each flavor owns distinct root-level keys
- Clean workloadRef transition: deprecate individual fields, not a whole tree
- Better UX: `spec.image` instead of `spec.workload.template.spec.containers[0].image`

## What this does NOT achieve

- Does NOT eliminate function-asya-flavors entirely (dynamic EnvironmentConfig
  selection via Requirements API still needs custom code)
- Does NOT allow using function-patch-and-transform for merging
  (keepMapValues is shallow, not deep-merge)

## Design constraints

- Flavors are non-intersecting by design (each flavor owns a distinct concern)
- Env vars do NOT belong in flavors (secrets are namespace-scoped)
- Actor inline spec always wins over flavor values
- Must preserve workloadRef path for future bring-your-own-deployment support
- Must preserve custom volume/secret mounting into workload

## Scope

- XRD schema change (breaking)
- All 3 compositions rewritten (render-deployment reads flat fields)
- Injector updates (reads container spec from new paths)
- All test manifests and examples updated
- Migration guide for existing AsyncActors
- Simplify function-asya-flavors to ~30 LOC flat merge

## Depends on

- u5pd (ship current simplified merge as v0, then this replaces it)
