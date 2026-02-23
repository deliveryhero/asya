---
title: Fix transient WorkloadError state during actor scale-up
priority: 2 # medium
type: task
reason: Not present after migration to Crossplane
---



## Problem

Actors show transient WorkloadError state when scaling up, even though the issue resolves itself within seconds.

## Observed Behavior

```
# Initial state - WorkloadError
hello       hello       WorkloadError   1         9         11      11        0     30    0s ago (up)     4h33m

# 2 seconds later - Running
hello       hello       Running   11        0         11      11        0     30    2s ago (up)     4h33m
```

The actor transitions from:
- 1 running, 9 failing pods → WorkloadError
- 11 running, 0 failing pods → Running (after ~2 seconds)

## Context

- This issue was thought to be fixed previously (check main branch history)
- Need to investigate if this is a race condition during rapid scaling
- May be related to pod readiness checks or status reconciliation timing

## Investigation Needed

1. Review previous fix in git history
2. Check operator reconciliation logic for status computation
3. Examine pod readiness probe timing vs status updates
4. Verify KEDA scaling event timing vs pod creation
5. Look for race conditions in workload status calculation

## Acceptance Criteria

- Actors should not show WorkloadError during normal scale-up operations
- If transient failures are expected, status should reflect "Scaling" or similar
- Document expected behavior for rapid scaling scenarios


---
_Migrated from beads `asya-4js`_
