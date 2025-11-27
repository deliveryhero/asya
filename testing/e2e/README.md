# Asya🎭 E2E Tests

End-to-end tests with Kind (Kubernetes in Docker).

## Quick Start

```bash
cd testing/e2e
export PROFILE=rabbitmq-minio   # or sqs-s3
make up                         # Deploy cluster (~5-10 min)
make diagnostics                # Run diagnostics on the current E2E environment
make logs                       # Show recent logs from all Asya🎭 components
make port-forward-up
make trigger-tests              # Run tests against Kind cluster
make port-forward-down
make cov                        # Print coverage info
```

If you prefer to stay at the repo root, you can prefix commands like so: `PROFILE=rabbitmq-minio make -C testing/e2e <target>`.

## Prerequisites

- Kind v0.20.0+
- kubectl v1.28+
- Helm v3.12+
- Helmfile v0.157+
- Docker v24+
