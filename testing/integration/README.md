# Integration Tests

This directory contains integration tests for the Asya🎭 framework, organized into test suites that validate component interactions.

## Directory Structure

```
testing/integration/
├── Makefile                    # Unified integration test orchestration
├── compose/             # Shared docker-compose configurations
│   ├── base.yml               # Base configuration (RabbitMQ, volumes, logging)
│   └── rabbitmq.conf          # RabbitMQ configuration
├── sidecar/                   # Sidecar-Runtime socket integration tests (Go)
│   ├── socket_integration_test.go
│   ├── go.mod
│   └── go.sum
├── sidecar-runtime/           # Sidecar-Runtime pipeline tests (Python + Docker)
│   ├── docker-compose.yml     # Test-specific services (runtimes + sidecars)
│   ├── rabbitmq-definitions.json
│   └── tests/                 # Test files, Dockerfile, requirements
├── gateway/                   # Gateway integration tests (Go)
│   ├── jobs/                  # PostgreSQL job store tests
│   ├── queue/                 # RabbitMQ connection pool tests
│   ├── docker-compose.yml
│   ├── go.mod
│   └── go.sum
├── gateway-actors/            # Gateway-to-Pipeline integration tests (Python)
│   ├── docker-compose.yml     # Test-specific services (gateway + actors + infrastructure)
│   ├── gateway-routes.yaml    # Gateway route configuration
│   ├── rabbitmq-definitions.json
│   └── tests/                 # Test files, Dockerfile, requirements
└── operator/                  # Operator integration tests (Go + envtest)
    ├── asyncactor_test.go
    ├── suite_test.go
    └── testdata/
```

## Test Suites

### sidecar (Go socket tests)

Tests Go sidecar ↔ Python runtime Unix socket communication without RabbitMQ:

- Socket protocol validation
- Error handling (exceptions, OOM, CUDA OOM, timeouts)
- Fanout patterns
- Edge cases (empty responses, large payloads, Unicode)
- Mock transport (no RabbitMQ)

**Technology**: Go tests using `asya-sidecar/pkg/testing` public API
**Coverage**: 38.5% sidecar code

### sidecar-runtime (Docker pipeline tests)

Tests the interaction between sidecars and runtimes with real RabbitMQ:

- Envelope routing through queues
- Error handling (exceptions, OOM, CUDA OOM, timeouts)
- Fanout patterns
- Multi-actor pipelines

**Technology**: Python tests with Docker Compose (RabbitMQ + sidecars + runtimes)

### gateway (Go integration tests)

Tests gateway components with real infrastructure:

- PostgreSQL job store (CRUD operations)
- RabbitMQ connection pooling
- Queue operations

**Technology**: Go tests with Docker Compose (PostgreSQL + RabbitMQ)

### gateway-actors (Full pipeline tests)

Tests the full pipeline including gateway, actors, and end handlers:

- Gateway MCP API (JSON-RPC 2.0, SSE streaming)
- Multi-actor pipelines with progress tracking
- S3 persistence (happy-end, error-end actors)
- Handler modes (payload vs envelope)

**Technology**: Python tests with Docker Compose (PostgreSQL + MinIO + RabbitMQ + gateway + actors)

### operator (envtest tests)

Tests operator CRD reconciliation logic:

- AsyncActor creation/update/deletion
- Sidecar injection
- KEDA integration
- Transport validation

**Technology**: Go tests with envtest (Kubernetes API without full cluster)

## macOS-Specific Setup

### Docker Compose Version Requirement

Integration tests require Docker Compose v2.17.0 or newer due to a [known bug in v2.16.0](https://github.com/docker/compose/issues/10258) that breaks `env_file` path resolution when using `extends`.

**Check your version:**
```bash
docker-compose --version
```

**If you have v2.16.0, upgrade Docker Compose:**

Option 1: Update Docker Desktop (recommended for macOS)
- Install or update [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/) to get the latest stable Compose v2
- Docker Desktop includes `docker compose` (plugin) which is the recommended way to run Compose v2

Option 2: Upgrade standalone docker-compose
```bash
brew upgrade docker-compose
```

**Configure environment:**
```bash
# If using Docker Desktop (docker compose plugin):
export DOCKER_COMPOSE="docker compose"

# If using standalone docker-compose:
export DOCKER_COMPOSE="docker-compose"
```

Add this to your `~/.zshrc` or `~/.bashrc` to make it permanent.

### Troubleshooting macOS Issues

**Error: `Failed to load .../envs/.env.postgres: no such file or directory`**

This indicates Docker Compose v2.16.0 is incorrectly resolving `env_file` paths when using `extends`. This is a [known regression bug](https://github.com/docker/compose/issues/10258) fixed in v2.17.0+.

Solution: Upgrade Docker Compose (see above).

**Verification:**
```bash
# After upgrading, verify the fix:
cd testing/integration/gateway
DOCKER_COMPOSE="docker-compose" make test  # or export DOCKER_COMPOSE="docker compose"
```

## Running Tests

### All integration tests
```bash
make test
```

### Individual test suites
```bash
make test-sidecar          # Sidecar socket tests (Go)
make test-sidecar-runtime  # Sidecar-runtime pipeline tests (Python + Docker)
make test-gateway          # Gateway tests (Go + Docker)
make test-gateway-actors   # Gateway-actors pipeline tests (Python + Docker)
make test-operator         # Operator tests (Go + envtest)
```

### Coverage
```bash
make cov-sidecar    # Sidecar socket test coverage
make cov-gateway    # Gateway integration test coverage
make cov-operator   # Operator integration test coverage
make cov            # All integration test coverage
```

### Cleanup
```bash
make clean  # Remove all containers and volumes
make down   # Stop containers
```

## Docker Compose Architecture

Both test suites use a **layered docker-compose configuration**:

1. **Base layer** (`compose/base.yml`): Shared services (RabbitMQ, logging, volumes)
2. **Test-specific layer** (`{suite}/docker-compose.yml`): Services unique to each test suite

### Example: Running sidecar-runtime tests

```bash
cd sidecar-runtime
docker compose -f ../compose/base.yml -f docker-compose.yml up
```

This approach:
- ✅ Eliminates configuration duplication
- ✅ Ensures consistent RabbitMQ/infrastructure setup
- ✅ Makes it easy to add new test suites
- ✅ Reduces maintenance burden

## Port Allocations

To avoid conflicts when running tests in parallel:

- **sidecar-runtime**: RabbitMQ on `5673:5672`, Management UI on `15673:15672`
- **gateway-actors**: RabbitMQ on `5674:5672`, Management UI on `15674:15672`, PostgreSQL on `5435:5432`, MinIO on `9005:9000`

## Handler Modes (gateway-actors only)

The gateway-actors tests run in **both handler modes** to ensure compatibility:

1. **Payload mode** (`ASYA_HANDLER_MODE=payload`):
   - Handlers receive only payload
   - Headers/route preserved automatically by runtime
   - Simplest programming model

2. **Envelope mode** (`ASYA_HANDLER_MODE=envelope`):
   - Handlers receive full envelope structure
   - Can modify headers, routes
   - Required for advanced routing logic

See `HANDLER_MODE_TESTING.md` in the gateway-actors directory for details.

## Coverage

Coverage data is stored in `.coverage/` at the test suite root:

```bash
make cov-integration  # View coverage report
```

Coverage JSON files:
- `cov-integration-sidecar-runtime.json`
- `cov-integration-gateway-actors.json`

## Adding New Test Suites

To add a new integration test suite:

1. Create directory: `tests/integration/new-suite/`
2. Add `docker-compose.yml` (references `../compose/base.yml`)
3. Add `rabbitmq-definitions.json` with queue definitions
4. Add `tests/` directory with Dockerfile, requirements.txt, test files
5. Update `tests/integration/Makefile` with new targets
6. Update root `Makefile` to include new suite in `test-integration`

## Migration Notes

This structure was migrated from:
- `tests/sidecar-vs-runtime/integration/` → `tests/integration/sidecar-runtime/`
- `tests/gateway-vs-actors/integration/` → `tests/integration/gateway-actors/`

Benefits of new structure:
- Shared infrastructure configuration
- Clearer naming (describes what's tested, not component pairs)
- Easier to extend with new test suites
- Consistent with `testing/component/`, `tests/e2e/` structure
