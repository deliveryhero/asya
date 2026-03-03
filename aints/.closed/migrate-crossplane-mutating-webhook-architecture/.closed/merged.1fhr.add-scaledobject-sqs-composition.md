---
title: Add ScaledObject to SQS Composition
priority: 2 # medium
dependencies:
  - 1cph/1favq5
---




Add KEDA ScaledObject resource to the SQS Composition to enable autoscaling.

## Tasks

1. Add ScaledObject resource to composition-sqs.yaml using go-templating
2. Configure SQS trigger with queue URL from composed Queue
3. Set scaling parameters from spec.scaling (min/max replicas, polling interval, cooldown, queue length)
4. Reference Deployment as scaleTargetRef
5. Test ScaledObject creation with sample AsyncActor

## Acceptance Criteria

- ScaledObject created alongside SQS Queue
- ScaledObject targets the Deployment correctly
- Scaling parameters from AsyncActor spec are applied

## Technical Notes

- ScaledObject needs TriggerAuthentication reference (added in Phase 3.2)
- For initial testing, use static AWS credentials or skip auth
- scaleTargetRef should match the Deployment name pattern

## Dependencies

- Requires Deployment to be added to Composition first (or use workloadRef)


---
**Close reason**: Already implemented in commits 6fb9a1a and d2e1790


---
_Migrated from beads `asya-pvh`_
