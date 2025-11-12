# Runtime ConfigMap Component Tests

Component tests that validate the operator creates ConfigMaps with the real `asya_runtime.py`.

## Overview

These tests verify that:
1. The operator correctly reads runtime from `/runtime/asya_runtime.py`
2. ConfigMaps are created with proper labels and no owner references (shared resource)
3. The runtime can be updated when ConfigMaps already exist

## Test Cases

✅ **No Ownership**: ConfigMap has no owner references (shared across actors)
✅ **Shared Between Actors**: Multiple actors can share the same ConfigMap
✅ **Updates Existing**: ConfigMap can be updated with new runtime content

### Runtime Validation

Tests validate the ConfigMap contains the **real runtime** by checking for:
- `def handle_requests():` - Main entry point
- `def _load_function():` - Handler loading logic
- Absence of placeholder markers

## Running Tests

```bash
# From project root
make test-component

# From this directory
make test

# Clean up
make clean
```

## Test Structure

- **`configmap_test.go`**: Test cases that verify ConfigMap reconciliation
- **`docker-compose.yml`**: Test environment that mounts real runtime at `/runtime/asya_runtime.py`
- **`Makefile`**: Test execution targets

## How It Works

1. **Test setup**: Docker mounts `src/asya-runtime/asya_runtime.py` → `/runtime/asya_runtime.py`
2. **Operator reads**: Operator reads runtime from `/runtime/asya_runtime.py` at runtime
3. **Tests**: Verify the ConfigMap contains the real runtime

## Source Files

- **Real runtime**: `src/asya-runtime/asya_runtime.py` (source of truth)
- **Runtime path in operator**: `/runtime/asya_runtime.py` (mounted in tests, copied in production)
- **Component tests**: This directory (validates real runtime in ConfigMaps)
