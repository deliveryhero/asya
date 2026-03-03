---
title: Add Deployment status patching to Composition
priority: 2 # medium
dependencies:
  - 1fav
---




Patch Deployment status back to AsyncActor composite resource.

## Tasks

1. Add ToCompositeFieldPath patches for Deployment status
2. Patch status.infrastructure.workload.ready from Deployment conditions
3. Patch status.readyReplicas from Deployment status
4. Patch status.totalReplicas from Deployment status
5. Update phase derivation logic to include workload status

## Acceptance Criteria

- AsyncActor status shows workload readiness
- Ready/total replicas visible in status
- kubectl get asyncactors shows replica count

## Technical Notes

- Deployment exposes .status.conditions with type Available
- .status.readyReplicas and .status.replicas for counts


---
**Close reason**: Implemented in PR #140


---
_Migrated from beads `asya-bzv`_
