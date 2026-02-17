---
title: "Phase 3.5: Manually test full actor lifecycle (create, scale, delete)"
status: open
priority: 2 # medium
type: task
dependencies:
  - 1cph/1cf7
  - 1cph/1cpa
  - 1cph/1cgm
  - 1cph/1c01
  - 1cph/1cfr
  - misc/1cvi
  - misc/1cfy
---

Comprehensive integration test for AsyncActor lifecycle.

## Tasks

1. Test creation:
   - Create AsyncActor with workload
   - Verify SQS queue created
   - Verify KEDA ScaledObject created
   - Verify Deployment created with injected sidecar
2. Test scaling:
   - Send messages to SQS queue
   - Verify KEDA scales up pods
   - Drain queue, verify scale to zero
3. Test deletion:
   - Delete AsyncActor
   - Verify SQS queue deleted
   - Verify KEDA ScaledObject deleted
   - Verify Deployment deleted

## Acceptance Criteria

- Full lifecycle works end-to-end
- Resources cleaned up on deletion
- Scaling responds to queue depth
- New file docs/quickstart/README_CROSSPLANE.md is reproducible 

## Technical Notes

- Use LocalStack for SQS
- May need longer timeouts for Crossplane reconciliation
- Test both workload and workloadRef paths

## Way to test:
- cd into a temporary directory, create fresh kind cluster, create necessary files
- similar to docs/quickstart/README.md (first stage - just actor, without gateway or crew actors yet) perform manual tests
- don't create too many files - stay minimal
- your result file to commit should be docs/quickstart/README_CROSSPLANE.md
- if you find an error in XRD or integration with crossplane, fix it, redeploy, if needed, recreate kind cluster



## Reference

See docs/rfc/rfc-crossplane.md Section 9 (Phase 3)


---
**Close reason**: Full lifecycle tested: create->scale-up->process->scale-to-zero->delete. All Crossplane-managed resources cleaned up. Quickstart doc written. Chart and injector bugs fixed. PRs: #141 (chart fixes), crossplane-phase2 pushed.


---
_Migrated from beads `asya-qtk`_
