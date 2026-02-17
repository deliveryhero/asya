---
title: "Phase 4.1: Write E2E tests for Crossplane-based deployment"
status: done
priority: 2 # medium
type: task
dependencies:
  - 1cph/1cbq
  - 1cph/1c7x
---


Create comprehensive E2E test suite for the new Crossplane architecture.

## Tasks

1. Create new E2E test profile for Crossplane deployment
2. Test cases:
   - AsyncActor creation with SQS transport
   - Sidecar injection via webhook
   - Message processing through actor pipeline
   - KEDA scaling (up and down)
   - Scale to zero and wake up
   - Error handling (error-end routing)
   - Multi-actor pipelines
3. Verify existing E2E test scenarios work with new architecture
4. Update test infrastructure (Kind cluster setup)

## Acceptance Criteria

- All existing E2E test scenarios pass
- New Crossplane-specific tests added
- Tests run in CI pipeline
- Test coverage comparable to current operator tests

## Technical Notes

- May need to run Crossplane + old operator tests in parallel during transition
- Use existing testing patterns from testing/e2e/
- LocalStack for SQS

## Reference

See docs/rfc/rfc-crossplane.md Section 9 (Phase 4)


---
**Close reason**: Completed in commits 5f55c37 (feat(e2e): Migrate E2E tests to Crossplane architecture #149) and fbebc33 (fix(e2e): Add warm-up to concurrent envelope test #155). All E2E tests migrated to Crossplane + Injector architecture with adapted test infrastructure, chaos tests, and flaky test fixes.


---
_Migrated from beads `asya-rp7`_
