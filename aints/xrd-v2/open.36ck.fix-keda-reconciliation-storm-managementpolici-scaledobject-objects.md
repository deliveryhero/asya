---
title: "Fix KEDA reconciliation storm: managementPolicies on ScaledObject Objects"
priority: 2 # medium
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

Trade-off: XR won't reflect real-time ScaledObject health. Acceptable because XR
readiness depends on Deployment + Queue, not ScaledObject. KEDA scaling works
independently regardless of Crossplane status tracking.

## Testing

- pubsub-gcs profile most affected (persistent KEDA PubSub auth errors)
- sqs-s3 also affected when LocalStack SQS unavailable
- Verify XR version no longer climbs rapidly after fix
- Verify Phase 8 timeout can return to 300s once storm eliminated
