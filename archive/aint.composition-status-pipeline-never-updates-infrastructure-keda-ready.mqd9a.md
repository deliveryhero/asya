---
title: Composition status pipeline never updates infrastructure.keda.ready after ScaledObject becomes Ready
status: merged
priority: 2
assignee: Artem Yushkovskiy
parent: 00001
tags:
  - worktree:.worktrees/debt/mqd9.composition-status-pipeline-never-updates-infrastructure-keda-ready
  - branch:debt/mqd9.composition-status-pipeline-never-updates-infrastructure-keda-ready
  - pr:364
---

## Bug

When deploying AsyncActors to a new namespace, the XR status field
`infrastructure.keda.ready` stays `false` permanently even after the
KEDA ScaledObject reaches `READY=True`. This causes `phase: Creating`
to persist forever, even though the actor is fully functional.

## Observed Behavior

```
$ kubectl -n demo-skaffold get asyncactors
NAME     STATUS     READY   REPLICAS
x-sink   Creating   1       1          # stuck forever
x-sump   Creating   1       1

$ kubectl -n demo-skaffold get scaledobject x-sink
NAME     READY   ACTIVE
x-sink   True    False     # ScaledObject is READY=True
```

XR status detail:
```yaml
status:
  conditions:
  - reason: Available
    status: "True"
    type: Ready
  infrastructure:
    keda:
      ready: false       # never updated to true
    queue:
      ready: true
    workload:
      ready: true
  phase: Creating         # derived from keda.ready, stays forever
```

## Expected Behavior

After the ScaledObject becomes `READY=True`, the composition's status
pipeline should update `infrastructure.keda.ready: true` and the phase
should transition from `Creating` to `Napping` (if scaled to 0) or
`Ready` (if replicas > 0).

## Environment

- Cluster: GKE `gke_foodsci-img-gen-dev-1407-1448_europe-west1_asya-demo`
- Crossplane chart revision 5 (`helm upgrade --set transport=pubsub`)
- KEDA 2.x, ScaledObjects using `gcp-pubsub` trigger
- Namespace: `demo-skaffold` (new namespace, not the original `asya-demo`)

## Reproduction

1. Create a new namespace
2. Copy required secrets (`asya-runtime`, `asya-actor-creds`, `gcp-keda-secret`)
3. Set up WI annotation on default KSA
4. Deploy crew actors: `helm install asya-crew ... --namespace=<new-ns>`
5. Wait for ScaledObjects to become READY=True
6. Observe: `get asyncactors` shows `Creating` forever

## Root Cause Hypothesis

The composition function that patches `status.infrastructure.keda.ready`
from the ScaledObject's `.status.conditions[?(@.type=="Ready")].status`
either:
- Runs only once (at composition time, before ScaledObject exists)
- Has a missing or incorrect status match expression
- Doesn't re-observe composed resource status after initial creation

The `analyze` actor in the same namespace went through `Creating` ->
`Napping` successfully, but only after being deleted and recreated
(fresh ScaledObject created with the subscription already ready).

## Notes

This was discovered during the Skaffold vs Tilt build tool evaluation
(aint vppe). The actors are fully functional despite the stuck status --
pods run, queues are connected, KEDA scaling works. Only the display
status is wrong.
