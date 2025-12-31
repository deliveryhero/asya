# Asya🎭 E2E Tests

End-to-end tests with Kind (Kubernetes in Docker).

## Quick Start

All lifecycle commands require a profile: `PROFILE=rabbitmq-minio` (RabbitMQ + MinIO) or `PROFILE=sqs-s3` (LocalStack SQS + S3). Pick one, e.g.,

```bash
# Ensure PROFILE is exported before running the `make` commands. Otherwise, you may
# do `make test PROFILE=...` for each command, as shown at the bottom of the README file.
export PROFILE=rabbitmq-minio
```

 and run:

```bash
# Deploy cluster, run both handler modes + operator checks, then clean up
make test
```

For incremental debugging, run the individual targets:

```bash
# 1. Create/upgrade cluster (~5-10 min)
make up

# 2. Optional helpers while the cluster is running
make diagnostics
make logs

# 3. Trigger pytest suite (default ASYA_HANDLER_MODE=payload)
# Note: This target automatically manages port-forwarding for its duration.
make trigger-tests
# Run envelope mode explicitly if needed
make trigger-tests ASYA_HANDLER_MODE=envelope

# 4. Tear everything down
make down

# Coverage summary from the most recent run
make cov
```

## Profiles

- `rabbitmq-minio`: The default profile, using RabbitMQ for transport and MinIO for object storage.
- `sqs-s3`: LocalStack-backed SQS transport with S3-compatible storage for AWS parity testing.

Each profile maps to `profiles/<name>.yaml` and wires all Helm charts plus `.env.<name>` settings used by `scripts/deploy.sh`.

## Common Targets

- `make test PROFILE=...` – Full lifecycle (deploy → payload tests → envelope tests → operator scripts → cleanup).
- `make trigger-tests PROFILE=... [ASYA_HANDLER_MODE=payload|envelope]` – Run pytest suite against an existing cluster.
- `make diagnostics PROFILE=...` – Execute `scripts/debug.sh diagnostics` for the active cluster.
- `make logs PROFILE=...` – Tail recent logs across Asya components.
- `make port-forward-up|port-forward-down PROFILE=...` – Manage background port-forwards for gateway, RabbitMQ/SQS, etc.
- `make cov` – Print coverage info stored under `.coverage/testing/e2e`.

## Prerequisites

- Kind v0.20.0+
- kubectl v1.28+
- Helm v3.12+
- Helmfile v0.157+
- Docker v24+

## Platform-Specific Notes

### macOS

**Port-forwarding stability**: `kubectl port-forward` can be unstable on macOS when running tests in parallel. If you experience connection errors:

```bash
# Reduce parallel workers (recommended for macOS)
make trigger-tests PROFILE=sqs-s3 PYTEST_WORKERS=2

# Or run sequentially for maximum stability
make trigger-tests PROFILE=sqs-s3 PYTEST_WORKERS=1
```

The test framework includes automatic retry logic that restarts port-forwards when connections fail, but reducing parallelism improves stability.

**Debug failing tests**: Use fail-fast mode to stop on first failure:

```bash
make trigger-tests PROFILE=sqs-s3 PYTEST_WORKERS=2 PYTEST_OPTS="-v -x"
```

Default parallelism (`PYTEST_WORKERS=auto`) works well on Linux CI but may overwhelm port-forwards on macOS.

## Test Groups

E2E tests are organized into execution groups using pytest markers:

### Execution Order

1. **Regular tests** (unmarked, `@pytest.mark.fast`) - Run in parallel
2. **Chaos tests** (`@pytest.mark.chaos`) - Run serially (disrupt infrastructure)
3. **Docs tests** (`@pytest.mark.docs`) - Run serially, AFTER chaos (separate cluster)

### Docs Group: Quickstart README Validation

The `test_quickstart_readme_commands` test validates all bash commands in `docs/quickstart/README.md` against a real Kubernetes cluster.

**Characteristics**:
- **Dedicated cluster** - uses `asya-local` cluster (created by tutorial itself)
- **Runs LAST** - part of "docs" group with `@pytest.mark.order("last")`
- **Full isolation** - no conflicts with e2e infrastructure (separate cluster name)
- **Takes ~15 minutes** - cluster creation + infrastructure deployment + validation
- **Single cleanup** - `kind delete cluster --name asya-local` in post-fixture

**Fixture Lifecycle** (`quickstart_cluster`):
- **Pre**: Delete `asya-local` cluster if exists (ensures clean state)
- **Test**: Executes tutorial commands including `kind create cluster --name asya-local`
- **Post**: Delete `asya-local` cluster, restore kubectl context to e2e cluster

**To run manually**:

```bash
cd testing/e2e
uv run --with-editable ../../src/asya-testing pytest tests/test_quickstart_readme.py::test_quickstart_readme_commands -v
# Note: Fixture handles cleanup automatically, tutorial creates the cluster
```

**To run only docs tests**:

```bash
cd testing/e2e
uv run --with-editable ../../src/asya-testing pytest -m docs -v
```

This test is part of the regular CI suite and validates that the quickstart documentation actually works.
