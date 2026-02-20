---
title: "Fix XR Ready=False: add function-auto-ready to Composition pipeline"
status: done
priority: 2 # medium
type: task
tags:
  - type:bug
---




## Problem

The XAsyncActor XR (Composite Resource) shows Ready=False even when all
infrastructure is fully operational (SQS queue created, KEDA ScaledObject
active, Deployment running). The custom status.phase field correctly shows
"Ready", but Crossplane's native Ready condition stays False.

This causes:
- `kubectl get asyncactors` shows misleading Ready=False
- Tools/controllers that check XR conditions see the wrong status
- E2E tests had to work around this by checking status.phase instead of conditions
- deploy.sh Phase 8 had to use status.phase instead of Ready condition

## Root Cause

In Crossplane Pipeline mode, readiness is NOT automatically determined.
Functions in the pipeline must explicitly tell Crossplane when composed
resources are ready. Our Composition (composition-sqs.yaml) creates resources
via function-go-templating but never signals readiness back to Crossplane.

The Composition already computes correct readiness in the
"patch-status-and-derive-phase" step (checking queue Ready, ScaledObject Ready,
Deployment Available), but this is only written to status.phase — it never
tells Crossplane's control plane that the XR itself is ready.

## Solution: Add function-auto-ready

Install crossplane-contrib/function-auto-ready (v0.6.0) and add it as the
last pipeline step in composition-sqs.yaml:

```yaml
pipeline:
  # ... existing steps ...
  - step: automatically-detect-ready-composed-resources
    functionRef:
      name: function-auto-ready
```

### How function-auto-ready works

1. Checks each composed resource (SQS Queue, Kubernetes Objects)
2. For native Crossplane resources (Queue): checks their Ready condition
3. For Kubernetes provider Objects: checks the Object's own Ready condition
   (set to True when the inner manifest is successfully applied)
4. For standard K8s resources: has built-in health checks
   (Deployments: checks availableReplicas, etc.)
5. When ALL composed resources pass: marks XR as Ready=True

### What this means for readiness semantics

After the fix, two readiness signals will exist:
- XR Ready=True: "Crossplane has provisioned all composed resources"
  (Object resources applied, Queue created)
- status.phase=Ready: "All infrastructure is actually healthy and serving"
  (Deployment available, ScaledObject active, Queue responsive)

Both are useful at different levels. The deploy.sh and tests can switch back
to checking the XR Ready condition for basic readiness.

## Implementation Steps

1. Add function-auto-ready to providers.yaml:
   ```yaml
   apiVersion: pkg.crossplane.io/v1
   kind: Function
   metadata:
     name: function-auto-ready
   spec:
     package: xpkg.upbound.io/crossplane-contrib/function-auto-ready:v0.6.0
   ```

2. Add to values.yaml:
   ```yaml
   functions:
     autoReadyVersion: "v0.6.0"
   ```

3. Add as last pipeline step in composition-sqs.yaml:
   ```yaml
   - step: automatically-detect-ready-composed-resources
     functionRef:
       name: function-auto-ready
   ```

4. Wait for provider to become healthy before deploying ProviderConfigs
   (same Phase 6b pattern already in deploy.sh)

5. Update tests:
   - Revert wait_for_asyncactor_ready to check XR Ready condition again
   - Remove status.phase workaround from deploy.sh Phase 8
   - Verify test_asyncactor_status_conditions passes without xfail

6. Test on clean Kind cluster to verify XR shows Ready=True

## Files to Modify

- deploy/helm-charts/asya-crossplane/templates/providers.yaml (add Function)
- deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml (add pipeline step)
- deploy/helm-charts/asya-crossplane/values.yaml (add version)
- src/asya-testing/asya_testing/utils/kubectl.py (optionally revert to condition check)
- testing/e2e/scripts/deploy.sh (optionally revert Phase 8 to condition check)

## References

- function-auto-ready: https://github.com/crossplane-contrib/function-auto-ready
- Crossplane Pipeline readiness: functions signal readiness via composed resource status
- Current workaround: status.phase check in kubectl.py and deploy.sh (commit 961e562)


---
## Notes

## Tests to review/unmute after fix

### Workarounds to revert (not skipped, but worked around in code):
- src/asya-testing/asya_testing/utils/kubectl.py: wait_for_asyncactor_ready()
  currently checks status.phase instead of XR Ready condition — revert to
  check conditions after fix
- testing/e2e/scripts/deploy.sh Phase 8: currently checks status.phase
  instead of XR Ready condition — revert to check conditions after fix

### Queue health monitoring tests to UN-SKIP (4 tests):
These were skipped with reason "operator queue health checks not applicable"
but Crossplane's AWS provider handles drift detection automatically — if a
queue is deleted externally, Crossplane should recreate it during its next
reconciliation cycle (~1 min). After fixing XR Ready=False, un-skip these
and verify they pass with Crossplane drift reconciliation:

- tests/test_queue_health_monitoring_e2e.py::test_operator_recreates_deleted_actor_queue_e2e
- tests/test_queue_health_monitoring_e2e.py::test_operator_recreates_deleted_system_queue_e2e
- tests/test_queue_health_monitoring_e2e.py::test_multiple_queue_deletions_e2e
- tests/test_queue_health_monitoring_e2e.py::test_queue_deletion_during_processing_e2e

### KEDA scaling tests to FIX (9 tests — namespace mismatch bug):
These are skipped because the fixture checks for keda-operator in namespace
"keda" but it's deployed in namespace "asya-e2e". Fix the namespace in the
fixture, then verify tests work with Crossplane-managed ScaledObjects:

- tests/test_keda_scaling.py::test_scaledobject_created_with_scaling_enabled
- tests/test_keda_scaling.py::test_scaledobject_not_created_when_scaling_disabled
- tests/test_keda_scaling.py::test_advanced_scaling_configuration
- tests/test_keda_scaling.py::test_scaledobject_updated_on_asyncactor_change
- tests/test_keda_scaling.py::test_triggerauthentication_created_for_secrets
- tests/test_keda_scaling.py::test_scaledobject_owner_reference
- tests/test_keda_scaling.py::test_hpa_metrics_available_with_trigger_auth
- tests/test_keda_scaling.py::test_hpa_desired_replicas_after_pod_kill
- tests/test_keda_scaling.py::test_operator_requeues_until_hpa_created

### Scaling performance tests to REVIEW (2 xfailed tests):
These xfail because kubectl scale --replicas=0 conflicts with KEDA's
minReplicaCount=1. Could be fixed by using a test actor with minReplicas=0:

- tests/test_scaling_performance_e2e.py::test_cold_start_latency
- tests/test_scaling_performance_e2e.py::test_queue_backlog_processing


---
**Close reason**: Fixed by adding function-auto-ready (v0.6.0) to Composition pipeline. XR now correctly shows Ready=True. Reverted status.phase workarounds in kubectl.py and deploy.sh.


---
_Migrated from beads `asya-zpz2`_
