---
title: "Phase 1.3: Create SQS Composition (queue + KEDA + deployment)"
status: merged
priority: 1
parent: h0mji
dependencies:
  - 1f3z
  - 1fe3
---

Create the Crossplane Composition that maps AsyncActor to AWS SQS resources.

## Tasks

1. Create Composition YAML for transport=sqs
2. Define composed resources:
   - SQS Queue (sqs.aws.upbound.io/v1beta1/Queue)
   - KEDA ScaledObject (keda.sh/v1alpha1/ScaledObject)
   - KEDA TriggerAuthentication (for IRSA)
   - Deployment (if spec.workload provided)
   - ServiceAccount with IRSA annotation (one per namespace)
3. Configure resource naming: asya-{namespace}-{actor}
4. Set up patches to copy spec values to composed resources
5. Configure connection details (queue URL) to be written to status
6. Apply Composition and test with sample AsyncActor

## Acceptance Criteria

- Creating AsyncActor results in SQS queue in LocalStack
- KEDA ScaledObject created targeting the deployment
- Deployment created with correct labels (asya.sh/actor, asya.sh/inject)
- Queue URL visible in AsyncActor status

## Technical Notes

- Composition must handle conditional resource creation (workload vs workloadRef)
- Use Crossplane patches for field mapping
- Queue naming: asya-{namespace}-{actor-name}

## Reference

See docs/rfc/rfc-crossplane.md Section 7 (Crossplane Composition)


---
**Close reason**: Phase 1 Foundation complete: SQS Composition working with LocalStack


---
_Migrated from beads `asya-24d`_
