---
title: "Phase 1.2: Define AsyncActor XRD (CompositeResourceDefinition)"
status: done
priority: 1 # high
type: task
dependencies:
  - 1cph/1ci6
---



Create the Crossplane CompositeResourceDefinition (XRD) that defines the AsyncActor API.

## Tasks

1. Create XRD YAML defining the AsyncActor schema
2. Define spec fields:
   - transport (required): enum [sqs]
   - workload (optional): embedded pod template
   - workloadRef (optional): reference to existing deployment
   - scaling: minReplicas, maxReplicas, pollingInterval, cooldownPeriod
   - sidecar: image, resources overrides
   - runtime: pythonExecutable, handlerMode
3. Define status fields:
   - conditions (standard Crossplane)
   - phase (Creating, Running, Napping, etc.)
   - infrastructure (queue, keda, workload status)
4. Define printer columns for kubectl output
5. Apply XRD to cluster and verify with `kubectl get xrd`

## Acceptance Criteria

- XRD applied successfully
- `kubectl explain asyncactor.spec` shows full schema
- `kubectl get asyncactors` works (empty list initially)

## Technical Notes

- XRD goes in deploy/helm-charts/asya-crossplane/ or similar
- Use openAPIV3Schema for validation
- Namespace-scoped XRD (not cluster-scoped)

## Reference

See docs/rfc/rfc-crossplane.md Section 4 (AsyncActor XRD)


---
**Close reason**: Phase 1 Foundation complete: Crossplane v2.1 installed with providers, XRD created, SQS Composition working with LocalStack


---
_Migrated from beads `asya-0l0`_
