---
title: "Phase 2.6: Test webhook injection with sample workloads"
status: merged
priority: 1
parent: h0mji
dependencies:
  - 1fju
  - 1f7o
---

Create integration tests for the webhook injection flow.

## Tasks

1. Create test AsyncActor with sample configuration
2. Create test Deployment with asya.sh/inject=true label
3. Verify pod gets sidecar injected correctly
4. Verify all volumes mounted
5. Verify environment variables set correctly
6. Test rejection when AsyncActor not ready
7. Test rejection when AsyncActor not found
8. Add tests to testing/integration/ or testing/e2e/

## Acceptance Criteria

- End-to-end test: AsyncActor + Deployment → injected pod
- Sidecar container present and configured correctly
- Volumes mounted at correct paths
- Tests pass in CI

## Technical Notes

- Can reuse existing E2E test patterns from testing/e2e/
- Focus on injection correctness, not full actor functionality
- Test with LocalStack for SQS

## Reference

See docs/rfc/rfc-crossplane.md Section 9 (Phase 2)


---
**Close reason**: Closed


---
_Migrated from beads `asya-c19`_
