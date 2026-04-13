---
title: Fix KEDA desired replica calculation anomaly during load bursts
status: merged
priority: 1
parent: 00000
tags:
  - type:bug
---

## Problem

KEDA scaling shows erratic desired replica counts during load bursts:
1. Initial 1k messages → desired=11, running=0 (pods never start)
2. Additional load → desired drops from 11 to 1
3. Then desired increases back to 11 with failing pods

## Observed Behavior

**After initial 1k message burst:**
```
hello       hello       ScalingUp   0   0   0   11   0   30   0s ago (down)
```
- Desired: 11 (seems correct for queue depth)
- Running: 0 (pods never started - WHY?)
- Total: 0 (no pods created at all)

**After sending more load:**
```
# First observation - desired drops to 1
hello       hello       WorkloadError   0   1   1   1   0   30   2m ago (down)

# Second observation - desired back to 11
hello       hello       WorkloadError   0   10   11   11   0   30   2m ago (down)
```
- Desired flips: 11 → 1 → 11 (erratic)
- Pods finally start but all fail (0 running, 10 failing)

## Load Test Script

```bash
for i in {1..5000}; do
  curl -s -X POST http://localhost:8080/tools/call \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"hello\", \"arguments\": {\"name\": \"Load-$i\"}}"
  sleep 0
done
```

## Investigation Needed

1. **KEDA ScaledObject configuration**:
   - Check queue depth polling interval
   - Verify target messages per replica (avgMsgCount)
   - Review cooldown periods and polling intervals

2. **Queue depth calculation**:
   - Why does desired=11 but no pods start?
   - Check if KEDA sees queue depth correctly
   - Verify queue depth metric source (RabbitMQ management API)

3. **Replica count oscillation**:
   - Why does desired drop from 11→1 when MORE load arrives?
   - Check for race conditions in KEDA metric collection
   - Review KEDA logs during scale events

4. **Pod startup failures**:
   - Why do pods fail when they finally start?
   - Check pod events: `kubectl describe pod -l app=hello`
   - Review sidecar/runtime logs for startup errors
   - Verify queue credentials and connectivity

5. **Operator reconciliation**:
   - Check if operator creates Deployment/StatefulSet when desired>0
   - Verify KEDA HPA targets correct workload
   - Review operator logs during scaling events

## Acceptance Criteria

- KEDA desired replicas should increase monotonically with queue depth
- Pods should start immediately when desired>0
- No erratic desired count changes (11→1→11)
- Pods should start successfully and become ready
- Document expected KEDA behavior for burst loads

## Reproduction Steps

1. Deploy actor with min=0, max=30
2. Send 1k messages rapidly (sleep 0)
3. Observe `kubectl get asya` - should see desired=11, running=0
4. Send 5k more messages
5. Observe desired drops to 1, then increases to 11
6. Pods fail to start properly

## Priority Justification

P1 (high) - This breaks autoscaling entirely. Actors don't scale up during load bursts, defeating the core value proposition.


---
## Notes



✅ **PR CREATED: https://github.com/deliveryhero/asya/pull/125**

Fix ready for review and merge.



---
**Close reason**: Fixed KEDA autoscaling bug. Operator now explicitly clears deployment.Spec.Replicas when KEDA enabled, giving HPA full control. Verified in asya-local cluster - pods now scale correctly based on queue depth. PR #125 created.


---
_Migrated from beads `asya-hbk`_
