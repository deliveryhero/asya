---
title: "Phase 3.1: Add IRSA ServiceAccount to Composition"
status: merged
priority: 2
dependencies:
  - 1fd2
---

Configure ServiceAccount with IAM Roles for Service Accounts (IRSA) in the Crossplane Composition.

## Tasks

1. Add ServiceAccount resource to SQS Composition
2. Configure IRSA annotation: eks.amazonaws.com/role-arn
3. One ServiceAccount per namespace: asya-actors
4. Reference ServiceAccount in Deployment pod template
5. Document IAM role requirements for production
6. Test with LocalStack (IRSA simulation or skip)

## Acceptance Criteria

- ServiceAccount created with correct IRSA annotation
- Deployment references the ServiceAccount
- Pods can access SQS without explicit credentials (in production)

## Technical Notes

- ServiceAccount naming: asya-actors (shared per namespace)
- IAM role ARN pattern: arn:aws:iam::ACCOUNT:role/asya-actors-{namespace}
- LocalStack may not fully support IRSA - document workaround

## Reference

See docs/rfc/rfc-crossplane.md Section 7 (ServiceAccount)


**Close reason**: Implemented in feature/crossplane-phase3-1


_Migrated from beads `asya-ymb`_
