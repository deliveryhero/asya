# Operator E2E Tests

End-to-end tests for AsyncActor operator covering critical production scenarios.

**Location**: `/testing/e2e/operator/`

## Test Suite

1. **01-startup-reconciliation.sh** - Operator startup reconciliation for existing AsyncActors without workloads
2. **02-deletion-finalizer.sh** - AsyncActor deletion, finalizer cleanup, and cascading resource removal
3. **03-spec-updates.sh** - AsyncActor spec updates (transport, scaling, replicas)
4. **04-keda-lifecycle.sh** - KEDA ScaledObject creation, deletion, and configuration updates
5. **05-transport-validation.sh** - Transport registry validation and error handling
6. **06-sidecar-injection.sh** - Sidecar injection with user container conflicts
7. **07-concurrent-operations.sh** - Concurrent AsyncActor creation and updates

## Running Tests

```bash
# Run all operator E2E tests
cd testing/e2e && make test-operator-e2e

# Run individual test
cd testing/e2e/operator && ./01-startup-reconciliation.sh
```

## Prerequisites

- Kind cluster running (asya-e2e)
- kubectl configured
- Operator deployed to asya-system namespace
