---
title: Fix operator ↔ KEDA race condition in deployment reconciliation
priority: 2 # medium
tags:
  - type:bug
---







## Problem

The asya-operator uses controllerutil.CreateOrUpdate() to reconcile deployments, creating a race condition with KEDA's HPA controller:

1. Operator reads Deployment (generation N)
2. KEDA HPA updates Deployment.spec.replicas (generation N+1)
3. Operator tries to write changes expecting generation N
4. Kubernetes rejects with 'object has been modified' error
5. Exponential backoff retry loop ensues

## Evidence

- Deployment generation: 257 (normal is ~10-20 over 70 minutes)
- Error rate: ~10 'object has been modified' conflicts per minute
- Pod churn: Rapid create/delete cycles during scaling
- Status lag: AsyncActor.status shows stale desiredReplicas (up to 11 minutes old)

## Affected AsyncActors

- chaos-slow: 646 messages queued, stuck at 1 replica (should be 2)
- happy-end: ScalingUp status is 11 minutes stale
- Deployment generation approaching 300+

## Root Cause Analysis

File: src/asya-operator/internal/controller/asya_controller.go:1267

The CreateOrUpdate() function opens a 'read-then-write' window:
- Reads current deployment state
- Executes closure with desired state
- Writes result back

KEDA updates spec.replicas during this window, causing conflicts.

## Solution

Replace CreateOrUpdate() with strategic merge patch:
- Read deployment once
- Prepare changes (no write yet)
- Patch only fields operator owns (template, labels, metadata)
- Never touch spec.replicas (KEDA owns this exclusively)
- Atomic patch eliminates race condition

## Expected Outcome

After fix:
- Deployment generation stabilizes <20/min (currently 3/sec)
- 'object has been modified' errors drop to 0
- KEDA scaling success rate: 99%+ (currently ~40%)
- AsyncActor status updates within 2 seconds (currently 5-15 seconds)
- Queue backlogs clear properly

## Implementation

1. Extract reconcileDeployment closure logic to helper function (applyDeploymentUpdates)
2. Replace CreateOrUpdate with Get + Patch pattern
3. Ensure spec.replicas is never touched when KEDA enabled
4. Add unit tests for concurrent KEDA updates

Estimated effort: 2-3 hours including tests and verification

## Files Affected

- src/asya-operator/internal/controller/asya_controller.go (reconcileDeployment, new applyDeploymentUpdates)
- src/asya-operator/internal/controller/asya_controller_test.go (new tests)

## Verification

Post-fix verification:
- Deployment generation <20 in steady state
- kubectl logs | grep 'object has been modified' returns no results
- AsyncActor status.status syncs with HPA.status.desiredReplicas within 2 seconds
- K6 load test completes without queue backlog



---
## Notes

Implementation completed successfully. All PR review comments addressed.

Changes:
1. Replaced controllerutil.CreateOrUpdate() with Get + Patch pattern
2. Created applyDeploymentUpdates() helper function for update logic
3. Removed replicas=nil assignment to avoid KEDA update loop (PR review fix)
4. Removed unused ctx parameter from applyDeploymentUpdates (PR review fix)
5. Added e2e test for deployment generation stability under load

Key code changes in src/asya-operator/internal/controller/asya_controller.go:
- reconcileDeployment: Now uses Get + MergeFrom + Patch/Create pattern
- applyDeploymentUpdates: New helper with all deployment update logic
- Critical fix: Don't modify spec.replicas when KEDA enabled (preserves existing value)

Testing:
- All unit tests pass (updated migration test to verify preservation)
- New e2e test: test_deployment_generation_stability_under_keda_load
- Build successful
- All linters pass

Commits:
- a15f77f: fix(operator): Replace CreateOrUpdate with strategic merge patch
- 934970e: test(e2e): Add deployment generation stability test
- d7f3c90: fix(operator): Address PR review - remove replicas=nil update loop

Branch: fix/asya-puk-keda-race-condition
Worktree: /home/a.yushkovskiy/asya/.worktrees/asya-puk-keda-race-fix
PR: https://github.com/deliveryhero/asya/pull/131
Status: All review comments addressed and resolved

Next steps:
1. Await final PR approval
2. Merge to main
3. Monitor deployment generation and conflict errors in production


---
**Close reason**: PR closed; worktree cleaned up


---
_Migrated from beads `asya-puk`_
