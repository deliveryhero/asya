---
title: Add ScaledObject status patching to Composition
priority: 2 # medium
dependencies:
  - 1fhr
---





Patch KEDA ScaledObject status back to AsyncActor composite resource.

## Tasks

1. Add ToCompositeFieldPath patches for ScaledObject status
2. Patch status.infrastructure.keda.ready from ScaledObject conditions
3. Patch status.infrastructure.keda.desiredReplicas (if available)
4. Update phase derivation logic to include KEDA status

## Acceptance Criteria

- AsyncActor status shows KEDA readiness
- kubectl get asyncactors reflects scaling status

## Technical Notes

- ScaledObject exposes .status.conditions with type Ready
- May need to extract from conditions array


---
**Close reason**: Implemented in PR #140


---
_Migrated from beads `asya-6y2`_
