# Testing Guide

> See [CONTRIBUTING.md](../../CONTRIBUTING.md) for testing philosophy and conventions

## Quick Reference

```bash
# Recommended: Use Makefile targets
make test-unit          # All unit tests
make test-component     # Component tests (single component + lightweight mocks)
make test-integration   # Integration tests (multi-component)
make test-e2e           # End-to-end tests (requires Kind cluster)
make test               # Run all unit + integration tests
make cov                # Run all tests with coverage
```

## Test Pyramid

Asya🎭 uses a 4-level testing pyramid with strict isolation rules:

```
       /\      E2E (Kind cluster)       - User scenarios, real K8s     - SLOW
      /  \
     /____\    Integration              - Multi-component, real infra   - MEDIUM
    /      \
   /________\  Component                - Single component + mocks      - FAST
  /__________\ Unit                     - Pure logic, embedded in src/  - INSTANT
```

### Test Level Definitions

| Level | Location | Infrastructure | Port-Forward | Coverage |
|-------|----------|----------------|--------------|----------|
| **Unit** | `src/{component}/tests/` | None | ❌ Not allowed | Go/Python unit tests |
| **Component** | `testing/component/{component}/` | Docker Compose | ❌ Not allowed | Single component + mocks |
| **Integration** | `testing/integration/{suite}/` | Docker Compose | ❌ Not allowed | Multi-component, real services |
| **E2E** | `testing/e2e/` | Kind cluster | ✅ Allowed | Full stack, user scenarios |

### Key Testing Rules

1. **No port-forwarding in unit/component/integration tests**
   - Test code must run inside Docker Compose
   - Services communicate via Docker networks
   - Only E2E tests can use `kubectl port-forward`

2. **Real services in Docker Compose when possible**
   - Prefer Docker Compose over Kind for integration tests
   - Use Kind only for E2E tests requiring Kubernetes features
   - Examples: RabbitMQ, PostgreSQL, MinIO run in Docker Compose

3. **Unit tests are embedded in src/**
   - `src/asya-sidecar/tests/` - Sidecar unit tests
   - `src/asya-runtime/tests/` - Runtime unit tests
   - `src/asya-gateway/tests/` - Gateway unit tests
   - Run with `make test-unit` or component-specific commands

4. **Sidecar-runtime communication requires shared network namespace**
   - Sidecars communicate with runtimes via Unix sockets
   - In Docker Compose, sidecars MUST use `network_mode: "service:{runtime-service}"`
   - This shares the network namespace, enabling Unix socket communication
   - Without this, sidecar connections to runtime will hang indefinitely (Go's `net.Dial` on Unix sockets hangs if socket exists but is in different namespace)
   - ✅ Production: Not an issue - Kubernetes pods automatically share network namespace
   - ⚠️ Testing: Critical for Docker Compose integration/component tests


## Testing Infrastructure

### Docker Compose Structure

Component and integration tests use a modular Docker Compose architecture for maximum reusability:

```
testing/
├── shared/compose/                    # Shared infrastructure (reusable)
│   ├── rabbitmq.yml                   # RabbitMQ message transport
│   ├── sqs.yml                        # LocalStack SQS transport
│   ├── postgres.yml                   # PostgreSQL + migrations
│   ├── minio.yml / s3.yml             # Object storage
│   ├── asya/                          # Asya🎭 framework components
│   │   ├── gateway.yml                # MCP gateway service
│   │   ├── testing-actors.yml         # Test actor workloads
│   │   └── crew-actors.yml            # System actors (happy-end, error-end)
│   ├── configs/                       # Third-party service configs
│   │   ├── rabbitmq.conf
│   │   ├── sqs-queues.txt
│   │   └── minio-policy.json
│   └── envs/                          # Environment files for services
│       ├── .env.rabbitmq              # RabbitMQ connection config
│       ├── .env.sqs                   # SQS connection config
│       ├── .env.minio / .env.s3       # Storage config
│       ├── .env.postgres              # PostgreSQL config
│       ├── .env.asya-sidecar          # Sidecar environment
│       ├── .env.asya-runtime          # Runtime environment
│       └── .env.tester                # Test runner config
│
├── component/{component}/             # Component-level tests
│   ├── Makefile                       # Test targets (test, test-one, cov, down, clean)
│   ├── compose/                       # Local service definitions
│   │   ├── tester.yml                 # Test runner service
│   │   └── testing-actors.yml         # Component-specific actors (optional)
│   ├── profiles/                      # Test profiles (transport/storage combinations)
│   │   ├── .env.shared                # Profile-wide variables
│   │   ├── rabbitmq.yml               # Profile: RabbitMQ transport
│   │   └── sqs.yml                    # Profile: SQS transport
│   └── tests/                         # Pytest test files
│
└── integration/{suite}/               # Integration-level tests
    ├── Makefile                       # Test targets with parametrization
    ├── compose/                       # Local service definitions
    │   └── tester.yml
    ├── profiles/                      # Multi-variable profiles
    │   ├── .env.sqs-minio             # ASYA_TRANSPORT=sqs, ASYA_STORAGE=minio
    │   ├── .env.rabbitmq-minio        # ASYA_TRANSPORT=rabbitmq, ASYA_STORAGE=minio
    │   ├── sqs-minio.yml              # SQS + MinIO + Asya🎭 + tester
    │   └── rabbitmq-minio.yml         # RabbitMQ + MinIO + Asya🎭 + tester
    └── tests/                         # Pytest test files
```

### Profile Assembly Pattern

Profiles combine shared infrastructure, Asya🎭 components, and local services using Docker Compose's `include:` directive:

```yaml
# profiles/rabbitmq.yml
include:
  # Shared infrastructure (static)
  - path: ../../../shared/compose/rabbitmq.yml

  # Optional: Other infrastructure
  # - path: ../../../shared/compose/minio.yml

services:
  # Tester service (extends local definition)
  tester:
    extends:
      file: ../compose/tester.yml
      service: tester
    depends_on:
      rabbitmq:
        condition: service_healthy
    networks:
      - asya
```

**Multi-variable profiles** (integration tests):

```yaml
# profiles/sqs-minio.yml
include:
  # Infrastructure
  - path: ../../../shared/compose/sqs.yml
  - path: ../../../shared/compose/minio.yml
  - path: ../../../shared/compose/postgres.yml

  # Asya🎭 components with variable substitution
  - path: ../../../shared/compose/asya/gateway.yml
    env_file: .env.sqs-minio  # Provides ASYA_TRANSPORT=sqs, ASYA_STORAGE=minio

services:
  tester:
    extends:
      file: ../compose/tester.yml
      service: tester
    env_file:
      - ../../../shared/compose/envs/.env.${ASYA_TRANSPORT}  # Substituted to .env.sqs
      - ../../../shared/compose/envs/.env.${ASYA_STORAGE}    # Substituted to .env.minio
    depends_on:
      sqs-setup:
        condition: service_completed_successfully
      gateway:
        condition: service_healthy
```

### Dynamic Parametrization

Tests support dynamic parametrization via environment variables:

**Transport parametrization:**
```bash
# Component test with different transports
make test-one ASYA_TRANSPORT=sqs
make test-one ASYA_TRANSPORT=rabbitmq
```

**Multi-variable parametrization:**
```bash
# Integration test with transport + storage combinations
make test-one ASYA_TRANSPORT=sqs ASYA_STORAGE=minio ASYA_HANDLER_MODE=payload
make test-one ASYA_TRANSPORT=rabbitmq ASYA_STORAGE=s3 ASYA_HANDLER_MODE=envelope
```

**Environment file resolution:**
- Profile env file (`.env.sqs-minio`) defines: `ASYA_TRANSPORT=sqs`, `ASYA_STORAGE=minio`
- Variables substitute in included files:
  - `env_file: - ../envs/.env.${ASYA_TRANSPORT}` → `../envs/.env.sqs`
  - `env_file: - ../envs/.env.${ASYA_STORAGE}` → `../envs/.env.minio`

### Typical Makefile Structure

All component/integration test directories have a Makefile with these targets:

```makefile
# Required environment variables
ASYA_TRANSPORT ?= sqs                    # Transport: sqs, rabbitmq
ASYA_HANDLER_MODE ?= payload             # Handler mode: payload, envelope
ASYA_STORAGE ?= minio                    # Storage: minio, s3
export ASYA_TRANSPORT
export ASYA_HANDLER_MODE
export ASYA_STORAGE

# Docker Compose configuration
DOCKER_COMPOSE ?= docker compose
COMPOSE_FILES := -f profiles/$(ASYA_TRANSPORT).yml
COMPOSE_PROJECT := comp-sidecar-$(ASYA_TRANSPORT)  # Unique project name per transport

# Coverage configuration (codecov)
PROJECT_ROOT := $(shell git rev-parse --show-toplevel)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR))
COVERAGERC := $(PROJECT_ROOT)/.coveragerc
export COVERAGE_DIR
export COVERAGERC

# Targets
test: clean
	@echo "[.] Running all transport combinations"
	$(MAKE) test-one ASYA_TRANSPORT=sqs
	$(MAKE) test-one ASYA_TRANSPORT=rabbitmq

test-one: require-ASYA_TRANSPORT
	@echo "[.] Running tests with $(ASYA_TRANSPORT) transport"
	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) up --abort-on-container-exit --exit-code-from tester tester
	$(MAKE) down ASYA_TRANSPORT=$(ASYA_TRANSPORT)

cov: clean
	@echo "[.] Running coverage for all transports"
	$(MAKE) test-one ASYA_TRANSPORT=sqs PYTEST_OPTS="--cov --cov-report=json"
	$(MAKE) test-one ASYA_TRANSPORT=rabbitmq PYTEST_OPTS="--cov --cov-report=json"

down:
	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) down -v

clean:
	$(MAKE) down ASYA_TRANSPORT=sqs
	$(MAKE) down ASYA_TRANSPORT=rabbitmq
```

**Key Makefile features:**
- **Separate Docker Compose projects per transport**: `COMPOSE_PROJECT := comp-sidecar-$(ASYA_TRANSPORT)`
  - Allows parallel test runs without conflicts
  - Example: `comp-sidecar-sqs` and `comp-sidecar-rabbitmq` can run simultaneously
- **Required environment variables**: Use `require-ASYA_TRANSPORT` pattern
- **Coverage directory hierarchy**: `.coverage/{test-suite}/{transport}/cov.json`
- **Centralized .coveragerc**: All tests share `$(PROJECT_ROOT)/.coveragerc`

### Third-Party Service Configurations

Shared configurations for third-party services live in `testing/shared/compose/configs/`:

```
configs/
├── rabbitmq.conf              # RabbitMQ server config
├── sqs-queues.txt             # Queues to pre-create in LocalStack
├── minio-policy.json          # MinIO bucket policies
└── postgres-init.sql          # Database initialization scripts (optional)
```

**Mounted in compose files:**
```yaml
# rabbitmq.yml
services:
  rabbitmq:
    image: rabbitmq:3.13-management
    volumes:
      - ./configs/rabbitmq.conf:/etc/rabbitmq/rabbitmq.conf:ro
```

## Unit Tests

### All Components (Makefile)

```bash
make unit-tests                # All unit tests
make unit-tests-sidecar        # Sidecar only
make unit-tests-gateway        # Gateway only
make unit-tests-runtime        # Runtime only
```

### Individual Components

**Go (Operator, Sidecar, Gateway)**:
```bash
cd operator  # or src/asya-sidecar or src/asya-gateway
go test ./... -v

# With coverage
go test ./... -coverprofile=coverage.out
go tool cover -html=coverage.out
```

**Python (Runtime)**:
```bash
cd src/asya-runtime
uv run pytest tests/ -v

# With coverage: see make commands
```

## Integration Tests

Tests full message flow with RabbitMQ:

```bash
# Recommended: Makefile
make integration-tests                 # All integration tests
make integration-tests-sidecar         # Sidecar ↔ Runtime
make integration-tests-gateway         # Gateway ↔ Actors

# Cleanup after tests
make clean-integration
```

## E2E Kubernetes Tests

### Full Stack Test (Kind)

Complete deployment and verification:

```bash
cd tests/gateway-vs-actors/e2e
./scripts/deploy.sh          # Deploy full stack (~5-10 min)
./scripts/test-e2e.sh        # Run E2E tests
./scripts/cleanup.sh         # Delete cluster
```

Tests:
- MCP tool calls and envelope status API
- Progress tracking via SSE streaming
- Multi-actor pipeline routing
- Error handling and retries

### Parallel E2E Testing

E2E tests can run in parallel by profile. Each profile creates an isolated Kind cluster:

```bash
# Run different profiles in parallel (separate terminal windows)
PROFILE=rabbitmq-minio make test-e2e    # Creates cluster: asya-e2e-rabbitmq-minio
PROFILE=sqs-s3 make test-e2e            # Creates cluster: asya-e2e-sqs-s3
```

**Cluster isolation**:
- Cluster name: `asya-e2e-{profile}` (e.g., `asya-e2e-rabbitmq-minio`)
- Namespace: `e2e` (consistent across all profiles)
- kubectl context: `kind-asya-e2e-{profile}`

**Cleanup per profile**:
```bash
PROFILE=rabbitmq-minio make down   # Delete asya-e2e-rabbitmq-minio
PROFILE=sqs-s3 make down            # Delete asya-e2e-sqs-s3
```

**Resource requirements**:
- Each Kind cluster: ~2-4GB RAM + CPU
- Ensure sufficient system resources before running parallel tests

### Actor Deployment Tests

```bash
# Deploy actor
kubectl apply -f examples/asyas/simple-actor.yaml

# Check status
kubectl get asyas simple-actor
kubectl describe asya simple-actor

# Check resources
kubectl get deployment simple-actor
kubectl get pods -l asya.sh/actor=simple-actor

# Check logs
kubectl logs -l asya.sh/actor=simple-actor -c sidecar
kubectl logs -l asya.sh/actor=simple-actor -c runtime
```

### Autoscaling Tests

```bash
# Deploy actor
kubectl apply -f examples/asyas/simple-actor.yaml

# Check initial state (should be 0 replicas)
kubectl get deployment simple-actor
kubectl get hpa

# Send messages
kubectl exec -n asya deploy/rabbitmq -- rabbitmqadmin publish \
  exchange=asya routing_key=simple-actor \
  payload='{"route":{"actors": ["simple-actor"],"current":0},"payload":{"test":true}}'

# Watch scaling
watch kubectl get deployment simple-actor
kubectl get scaledobject simple-actor -o yaml
```

## Gateway Tests

### MCP Protocol Tests

```bash
cd src/asya-gateway/tests
go test -v
```

See [src/asya-gateway/tests/MCP_PROTOCOL_TESTS.md](../../src/asya-gateway/tests/MCP_PROTOCOL_TESTS.md).

### Manual MCP Testing

```bash
# Port-forward gateway
kubectl port-forward -n asya svc/asya-gateway 8080:8080

# Health check
curl http://localhost:8080/health

# Call tool (creates envelope)
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "process",
      "arguments": {"input": "test data"}
    },
    "id": 1
  }'

# Get envelope status
curl http://localhost:8080/envelopes/<envelope-id>

# Stream updates (SSE)
curl http://localhost:8080/envelopes/<envelope-id>/stream
```

## Load Testing

```bash
# Flood queue with messages
for i in {1..1000}; do
  kubectl exec -n asya deploy/rabbitmq -- rabbitmqadmin publish \
    exchange=asya routing_key=test-actor \
    payload="{\"route\":{\"actors\":[\"test-actor\"],\"current\":0},\"payload\":{\"id\":$i}}"
done

# Monitor scaling
watch kubectl get hpa
watch kubectl get deployment
kubectl top pods
```

## Debugging

### Logs

```bash
# Operator
kubectl logs -n asya-system -l app=asya-operator -f

# Gateway
kubectl logs -n asya -l app=asya-gateway -f

# Actor (both containers)
kubectl logs -l asya.sh/actor=my-actor -c sidecar -f
kubectl logs -l asya.sh/actor=my-actor -c runtime -f

# RabbitMQ
kubectl logs -n asya -l app=rabbitmq -f
```

### Resources

```bash
# AsyncActor
kubectl describe asya my-actor

# Deployment
kubectl describe deployment my-actor

# ScaledObject (KEDA)
kubectl describe scaledobject my-actor

# Events
kubectl get events --sort-by='.lastTimestamp'
kubectl get events --field-selector involvedObject.name=my-actor
```

## Common Issues

### Actor Not Scaling

```bash
# Check KEDA ScaledObject
kubectl get scaledobject my-actor -o yaml
kubectl logs -n keda -l app=keda-operator

# Check queue depth
kubectl exec -n asya deploy/rabbitmq -- rabbitmqctl list_queues

# Check HPA
kubectl get hpa
kubectl describe hpa keda-hpa-my-actor
```

### Messages Not Processing

```bash
# Check logs
kubectl logs -l asya.sh/actor=my-actor -c sidecar
kubectl logs -l asya.sh/actor=my-actor -c runtime

# Check queue bindings
kubectl exec -n asya deploy/rabbitmq -- rabbitmqctl list_bindings
```

### Socket Errors

```bash
# Check volume mounts
kubectl get pod <pod-name> -o yaml | grep -A 10 volumeMounts

# Check permissions
kubectl exec <pod-name> -c runtime -- ls -la /tmp/sockets
kubectl exec <pod-name> -c sidecar -- ls -la /tmp/sockets
```

## Port allocation
When running tests, we make sure that services running in docker and/or kind don't conflict on localhost's ports:

| Service       | Gateway Unit | Sidecar-vs-Runtime | Gateway-vs-Actors | Kind E2E            |
|---------------|--------------|--------------------|-------------------|---------------------|
| PostgreSQL    | 5434         | -                  | 5435              | (internal)          |
| RabbitMQ AMQP | 5671         | 5673               | 5674              | (internal)          |
| RabbitMQ Mgmt | 15671        | 15673              | 15674             | (internal)          |
| Gateway HTTP  | -            | -                  | 8081              | 8080 (port-forward) |
| MinIO         | -            | -                  | 9005/9006         | (internal)          |

## Next Steps

- [Development Guide](development.md) - Local development workflow
- [Deployment Guide](deploy.md) - Production deployment
- [Building Guide](building.md) - Custom image builds
