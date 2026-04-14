---
title: Adapt existing E2E tests for Crossplane architecture
status: merged
priority: 2
dependencies:
  - 1fm4
  - 1fj4
  - 1f20
  - 1fsq
---

Adapt the existing E2E test suite (testing/e2e/) to work with the new Crossplane + Mutating Webhook architecture instead of the old asya-operator.

## Prerequisite

This task should ONLY begin after ALL existing functionality is confirmed working on Crossplane:
- Basic actor lifecycle (create, scale, delete) - asya-qtk
- Gateway integration with Crossplane-managed actors
- Crew actors (happy-end, error-end) working with Crossplane
- Quickstart manual validation complete - asya-7ap

## Tasks

1. Update E2E cluster setup to install Crossplane, providers, XRD, Composition, and asya-injector webhook instead of asya-operator
2. Replace operator Helm chart deployment with Crossplane infrastructure
3. Adapt AsyncActor CRD-based test fixtures to use Crossplane XR (AsyncActor XR) format
4. Verify all existing test scenarios pass:
   - MCP tool calls through gateway
   - SSE streaming
   - Multi-actor pipelines
   - Error handling (error-end routing)
   - KEDA autoscaling (scale up/down, scale-to-zero)
5. Update CI pipeline to use new E2E setup
6. Ensure test infrastructure teardown cleans up Crossplane resources

## Acceptance Criteria

- All existing E2E test scenarios pass with Crossplane architecture
- No regression in test coverage
- CI pipeline runs successfully
- Cluster setup/teardown is reliable

## Technical Notes

- Reuse existing test patterns from testing/e2e/
- LocalStack for SQS (same as current setup)
- May need longer timeouts for Crossplane reconciliation vs operator
- Consider running old and new E2E tests in parallel during transition period


**Close reason**: E2E tests migrated to Crossplane architecture


_Migrated from beads `asya-rl0`_
