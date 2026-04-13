---
title: "Fix KEDA reconciliation storm: managementPolicies on ScaledObject Objects"
status: merged
priority: 2
parent: ip3ls
tags:
  - pr:293
---

## Problem

KEDA continuously writes ScaledObject status (auth errors, metric polling). Each write triggers
provider-kubernetes to re-enqueue the watched Object, which triggers an XR reconcile cycle.
Under load (14+ actors, pubsub auth errors), this creates a storm:

- test-error XR reached version 9906 in ~8 minutes (~120 reconciles/sec)
- Crossplane opens circuit breaker: "Circuit breaker is open"
- Circuit breaker suppresses reconcile -> function-auto-ready never runs -> XR stuck not Ready

Pre-existing on main, not caused by Phase 1.5.

## Root Cause

provider-kubernetes uses --enable-watches, which subscribes to Object resource changes.
When KEDA writes ScaledObject status, provider-kubernetes detects the change and re-triggers
the parent XR reconcile. Fix: prevent provider-kubernetes from tracking status writes.

## Fix

Set `watch: false` on ScaledObject Object specs in all three compositions:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha2
kind: Object
spec:
  watch: false  # Don't react to KEDA status writes
  forProvider:
    manifest:
      apiVersion: keda.sh/v1alpha1
      kind: ScaledObject
      ...
```

`managementPolicies` is NOT the right fix — removing "Update" stops provider-kubernetes
from pushing changes TO the ScaledObject, but the storm is caused by provider-kubernetes
watching changes FROM the ScaledObject (KEDA status writes). The `watch` field controls
the watch subscription itself.

Apply `watch: false` to ScaledObject Objects only. Keep watches on Deployment Objects
(XR readiness depends on Deployment health). TriggerAuthentication Objects can also
use `watch: false` (KEDA updates their status too, though less frequently).

`watch: false` only disables the inbound watch (provider-kubernetes reacting to external changes). It doesn't affect the outbound lifecycle:

- XR deleted → Crossplane deletes all composed resources → Object CR deleted → provider-kubernetes deletes the ScaledObject

That's the normal Crossplane ownership chain. `watch` controls observation, not ownership. The delete path is driven by Crossplane's garbage collection (composed resources
are owned by the XR), which works regardless of watch settings.

Same for create and update — if you change spec.scaling.maxReplicas on the XR, Crossplane re-reconciles, renders a new ScaledObject spec, and provider-kubernetes applies
it. The watch: false just means provider-kubernetes won't react when KEDA writes back status on that ScaledObject.

Trade-off: XR won't reflect real-time ScaledObject health. Acceptable because XR
readiness depends on Deployment + Queue, not ScaledObject. KEDA scaling works
independently regardless of Crossplane status tracking.

In practice, **this risk is low** for Asya because:

1. Nobody manually edits ScaledObjects — they're managed by Crossplane, not humans
2. If deleted, Crossplane re-creates on next reconcile — the poll-interval still triggers periodic reconciliation (just not on every KEDA status write). The ScaledObject
gets recreated within 1 poll cycle.
3. KEDA itself validates the ScaledObject — if the spec is wrong, KEDA reports errors in its own metrics/events, independent of Crossplane

The **one real risk**: if KEDA is completely broken (CRD removed, operator down), Crossplane won't know the ScaledObject is unhealthy. Autoscaling silently stops. But this
would be caught by:
- KEDA's own health monitoring
- Actors stuck at 0 replicas (visible in the XR's status.infrastructure.workload.readyReplicas)
- Alerting on queue depth growing without scaling response


## Testing

- pubsub-gcs profile most affected (persistent KEDA PubSub auth errors)
- sqs-s3 also affected when LocalStack SQS unavailable
- Verify XR version no longer climbs rapidly after fix
- Verify Phase 8 timeout can return to 300s once storm eliminated


##  Docs

Update docs `docs/internal/`. Something like docs/internal/composition-watch-policy.md — short doc explaining why ScaledObject/TriggerAuthentication Objects use `watch: false` and what the trade-off is. The aint [36ck] already has the rationale written out — just move it into a doc.

## Printer columns

No change needed. Look at the current columns:

additionalPrinterColumns:
- name: Status    → .status.phase
- name: Ready     → .status.infrastructure.workload.readyReplicas
- name: Replicas  → .status.infrastructure.workload.replicas
- name: Transport → .spec.transport
- name: Queue     → .status.queueUrl

These all come from Deployment status and Queue status — both still have watch: true. ScaledObject status was never surfaced in kubectl get asyncactor output. So nothing
changes from the user's perspective.
