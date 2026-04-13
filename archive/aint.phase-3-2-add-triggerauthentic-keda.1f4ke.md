---
title: "Phase 3.2: Add TriggerAuthentication for KEDA"
status: merged
priority: 2
parent: h0mji
dependencies:
  - 1fd2
---

Configure KEDA TriggerAuthentication for AWS authentication.

## Tasks

1. Add TriggerAuthentication resource to SQS Composition
2. Configure podIdentity provider: aws (for IRSA)
3. Reference TriggerAuthentication in ScaledObject
4. Test KEDA can read SQS queue metrics
5. Alternative: configure static credentials for testing

## Acceptance Criteria

- TriggerAuthentication created alongside ScaledObject
- ScaledObject references TriggerAuthentication
- KEDA can poll SQS queue for scaling decisions

## Technical Notes

- KEDA supports IRSA via podIdentity
- For LocalStack testing, may need static credentials
- TriggerAuthentication is per-actor (not shared)

## Reference

See docs/rfc/rfc-crossplane.md Section 7 (KEDA TriggerAuthentication)


---
**Close reason**: Fixed in PR https://github.com/deliveryhero/asya/pull/138


---
_Migrated from beads `asya-5n8`_
