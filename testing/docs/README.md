# Documentation Tests

This directory contains tests that validate documentation examples to ensure they work as written.

## Structure

```
testing/docs/
├── Makefile           # Test runner commands
├── pytest.ini         # Pytest configuration
├── conftest.py        # Minimal fixtures (project_root only)
└── tests/             # Documentation validation tests
    └── test_quickstart_readme.py
```

## Key Differences from E2E Tests

**Docs tests:**
- Run **independently** of e2e infrastructure
- Create their own Kind clusters (e.g., `asya-local`)
- Do not require `make up` or profiles
- Use minimal fixtures (just `project_root`)
- Focus on validating user-facing documentation

**E2E tests:**
- Require shared infrastructure (`make up PROFILE=sqs-s3`)
- Use Kind cluster `asya-e2e-{profile}`
- Use complex fixtures (gateway_client, kube_client, etc.)
- Test system behavior and integration

## Running Tests

```bash
# Run all docs tests
make test

# Run only quickstart test
make test-quickstart

# Run with custom options
make test PYTEST_OPTS="-v -x"

# Cleanup
make clean
```

## Adding New Documentation Tests

1. Create test file in `tests/`
2. Mark with `@pytest.mark.docs`
3. Use only `project_root` fixture (no e2e fixtures)
4. Ensure test can run independently (no shared infrastructure)

## CI Integration

Docs tests run separately from e2e tests in CI:
- No profile required
- No Kind cluster setup needed (tests create their own)
- Can run in parallel with other test suites
