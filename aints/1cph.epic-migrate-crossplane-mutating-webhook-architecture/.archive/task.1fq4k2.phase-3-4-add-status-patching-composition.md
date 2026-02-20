---
title: "Phase 3.4: Add status patching to Composition"
status: done
priority: 2 # medium
type: task
dependencies:
  - 1cph/1fd2ug
---




Configure Crossplane to patch AsyncActor status with composed resource status.

## Scope (Queue-only for now)

KEDA and Deployment status patching deferred to:
- asya-6y2: ScaledObject status patching
- asya-bzv: Deployment status patching
- asya-kdu: Complex phase derivation

## Tasks

1. Update XRD status schema:
   - Add infrastructure.queue.ready field
   - Keep phase field for derived status
2. Configure status patches in Composition:
   - Patch infrastructure.queue.ready from SQS Queue conditions
3. Derive simple phase (Ready/Creating) from queue status
4. Configure STATUS printer column for kubectl output

## Acceptance Criteria

- AsyncActor status shows queue ready state
- phase field shows Ready or Creating
- kubectl get asyncactors shows STATUS column

## Technical Notes

- Use go-templating for phase derivation (simple if/else)
- Complex phase logic (Running/Napping/Degraded) deferred to asya-kdu


---
**Close reason**: Implemented queue-only status patching. XRD updated with infrastructure.queue.ready field and Status printer column. Composition derives phase (Ready/Creating) from SQS Queue conditions.


---
_Migrated from beads `asya-74f`_
