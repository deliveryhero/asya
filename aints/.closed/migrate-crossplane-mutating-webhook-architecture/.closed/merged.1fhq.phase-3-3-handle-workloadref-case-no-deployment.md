---
title: "Phase 3.3: Handle workloadRef case (no Deployment creation)"
priority: 2 # medium
dependencies:
  - 1cph/1fd2ug
---





Support both workload and workloadRef in Composition for actor deployments.

## Tasks

1. Add Deployment creation for spec.workload case:
   - Create Kubernetes Deployment via Crossplane Kubernetes provider
   - Apply required labels (asya.sh/actor, asya.sh/inject=true)
   - Pass through workload template spec
2. Add conditional logic to skip Deployment for spec.workloadRef:
   - If spec.workload: create Deployment
   - If spec.workloadRef: skip Deployment creation
3. Add ScaledObject creation:
   - Target workload name (from workload) or workloadRef.name
   - Configure KEDA scaling parameters from spec.scaling
4. Document user requirements for workloadRef:
   - Add asya.sh/inject=true label
   - Add asya.sh/actor=X label
   - Trigger rollout after AsyncActor creation

## Acceptance Criteria

- workload case: Deployment created by Crossplane with correct labels
- workloadRef case: no Deployment created by Crossplane
- ScaledObject targets correct Deployment in both cases
- Webhook still injects sidecar on pod creation (existing behavior)

## Technical Notes

- Use Crossplane function-go-templating for conditional logic
- Kubernetes provider creates Deployment in actor namespace
- ScaledObject references deployment by name

## Reference

See docs/rfc/rfc-crossplane.md Section 6 (workloadRef Behavior)


---
**Close reason**: Implemented workload and workloadRef support in SQS Composition with Deployment and ScaledObject creation


---
_Migrated from beads `asya-xl9`_
