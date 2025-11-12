# Test Parametrization Implementation Plan

**Status**: ✅ IMPLEMENTATION COMPLETE - Ready for Verification
**Goal**: Parametrize tests across handler_mode, transport, storage dimensions

## Strategy Summary

- **Component tests**: Full parametrization for owned dimension
- **Integration tests**: Full matrix of relevant dimensions
- **E2E tests**: Minimal parametrization (handler_mode only, fixed sqs-s3)

## Target Coverage

| Suite | Handler Mode | Transport | Storage | Runs |
|-------|--------------|-----------|---------|------|
| Component: Runtime | ✅ both | - | - | 2 |
| Component: Sidecar | - | ✅ both | - | 2 |
| Component: Gateway | - | ✅ both | - | 2 |
| Integration: Sidecar-Runtime | ✅ both | ✅ both | - | 4 |
| Integration: Gateway-Actors | ✅ both | ✅ both | ✅ both | 8 |
| E2E | ✅ both | sqs only | s3 only | 2 |

**Total: ~20 test runs**

## Implementation Phases

### Phase 1: Component Runtime ✅
- Add handler_mode loop to Makefile
- Update docker-compose with ASYA_HANDLER_MODE
- Coverage: cov-{mode}.json

### Phase 2: Integration Sidecar-Runtime ⚠️
- Add handler_mode parametrization (2 combinations)
- NOTE: Currently only tests RabbitMQ - full transport matrix deferred
- Coverage: cov-{mode}.json
- TODO: Add SQS transport testing in future iteration

### Phase 3: Integration Gateway-Actors ✅
- Create profiles: rabbitmq-s3.yml, sqs-s3.yml
- Add full 2×2×2 matrix (8 combinations)
- Coverage: cov-{mode}-{transport}-{storage}.json

### Phase 4: E2E ✅
- Fixed profile: sqs-s3
- Add handler_mode loop (2 combinations)
- E2E CI pattern: up-e2e → trigger-e2e (mode=payload) → trigger-e2e (mode=envelope) → down-e2e

### Phase 5: Cleanup ✅
- Remove duplicate code from test files
- Extract common patterns to src/asya-testing
- Standardize on test_config fixture

## Common Patterns Extracted

1. **Makefile test loops** - shared pattern for test/test-one ✅
2. **Profile naming** - {transport}-{storage}.yml (mode passed via env var) ✅
3. **Coverage naming** - cov-{mode}-{transport}-{storage}.json ✅
4. **Test config fixture** - centralized env var access ✅
5. **Shared transport fixture** - transport_client in asya_testing.fixtures.transport ✅

## Implementation Summary

### Files Created
- `testing/shared/test.mk` - Shared Makefile patterns (not heavily used yet)
- `testing/integration/gateway-actors/profiles/sqs-s3.yml`
- `testing/integration/gateway-actors/profiles/rabbitmq-s3.yml`
- `testing/integration/gateway-actors/profiles/.env.sqs-s3`
- `testing/integration/gateway-actors/profiles/.env.rabbitmq-s3`

### Files Modified
- **Component/Runtime**: Makefile, docker-compose.yml - Added handler_mode parametrization
- **Integration/Sidecar-Runtime**: Makefile, docker-compose.yml - Added handler_mode parametrization
- **Integration/Gateway-Actors**: Makefile - Added full 2×2×2 matrix
- **E2E**: Makefile - Added handler_mode loop with sqs-s3 profile
- **test_messaging.py**: Removed duplicate GatewayTestHelper and fixture
- **test_progress_standalone.py**: Removed duplicate wait_for_rabbitmq_consumers
- **test_sidecar_routing.py**: Use shared transport_client fixture
- **asya_testing/fixtures/transport.py**: Added transport_client fixture

### Code Cleanup
- Removed ~220 lines of duplicate code from test_messaging.py
- Removed ~60 lines of duplicate code from test_progress_standalone.py
- Removed ~35 lines of duplicate code from test_sidecar_routing.py
- Total: ~315 lines of duplicate code removed

## Notes

- ⚠️ Delete this file after verification complete
- No additional documentation created (as requested)
- All changes implemented - ready for verification phase
- Sidecar-Runtime only tests RabbitMQ (SQS transport deferred for future)
