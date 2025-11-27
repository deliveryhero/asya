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
make trigger-tests

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
