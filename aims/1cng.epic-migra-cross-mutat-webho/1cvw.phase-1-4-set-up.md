---
title: "Phase 1.4: Set up provider credentials (AWS/LocalStack)"
status: open
priority: 1 # high
type: task
---

Configure Crossplane provider credentials for AWS (LocalStack in testing, real AWS in production).

## Tasks

1. Create ProviderConfig for provider-aws pointing to LocalStack
2. Configure static credentials secret for LocalStack access
3. Document production credential setup (IRSA vs access keys)
4. Test queue creation via Crossplane to verify credentials work
5. Add credential setup to E2E test Makefile

## Acceptance Criteria

- provider-aws can create SQS queues in LocalStack
- Credentials are stored in Kubernetes Secret
- ProviderConfig references the secret correctly
- E2E tests can run with LocalStack credentials

## Technical Notes

- LocalStack endpoint: http://localstack:4566
- Region: us-east-1 (LocalStack default)
- Access key/secret: test/test (LocalStack default)
- For production: document IRSA setup in docs

## Reference

See docs/rfc/rfc-crossplane.md Section 9 (Phase 1)


---
**Close reason**: Phase 1 Foundation complete: Crossplane v2.1 installed with providers, XRD created, SQS Composition working with LocalStack


---
_Migrated from beads `asya-9q0`_
