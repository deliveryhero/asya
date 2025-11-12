# Asya🎭 E2E Tests

End-to-end tests with Kind (Kubernetes in Docker).

## Quick Start

```bash
make up-e2e             # Deploy cluster (~5-10 min)
make diagnostics-e2e    # Run diagnostics on the current E2E environment
make logs               # Show recent logs from all Asya🎭 components
make port-forward-up-e2e
make trigger-tests-e2e  # Run tests against Kind cluster
make port-forward-down-e2e
make cov-e2e            # Print coverage info

```

## Prerequisites

- Kind v0.20.0+
- kubectl v1.28+
- Helm v3.12+
- Helmfile v0.157+
- Docker v24+
