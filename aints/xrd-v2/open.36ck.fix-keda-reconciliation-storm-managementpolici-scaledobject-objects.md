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

Set managementPolicies on ScaledObject Objects in all three compositions:

    managementPolicies: ["Create", "Observe", "Delete"]

This prevents provider-kubernetes from writing back on status changes, breaking the
feedback loop. Same pattern already used for pubsub subscriptions (read-only observe).

## Testing

- pubsub-gcs profile most affected (persistent KEDA PubSub auth errors)
- sqs-s3 also affected when LocalStack SQS unavailable
- Verify XR version no longer climbs rapidly after fix
- Verify Phase 8 timeout can return to 300s once storm eliminated
