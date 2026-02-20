---
title: Add Deployment to SQS Composition (workload case)
status: done
priority: 2 # medium
type: task
---



Add Deployment resource to the SQS Composition for the spec.workload case (Crossplane-managed workload).

## Tasks

1. Add conditional Deployment resource to composition-sqs.yaml
2. Only create Deployment when spec.workload is provided (not workloadRef)
3. Copy workload template to Deployment spec
4. Add required labels: asya.sh/actor, asya.sh/inject=true
5. Configure resource naming: {actor-name} in the claim namespace
6. Test Deployment creation with sample AsyncActor

## Acceptance Criteria

- Deployment created when spec.workload is provided
- Deployment has correct labels for webhook injection
- Deployment template matches spec.workload

## Technical Notes

- Use go-templating for conditional logic
- Deployment should NOT be created if workloadRef is used
- Labels are critical for asya-injector webhook to inject sidecar


---
**Close reason**: Already implemented in commit 6fb9a1a


---
_Migrated from beads `asya-hm3`_
