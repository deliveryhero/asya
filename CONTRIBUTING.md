# Contributing to Asya🎭

## Development Setup

### Prerequisites

- Go 1.23+
- Python 3.13+
- **[uv](https://github.com/astral-sh/uv)** (required for Python development)
- Docker and Docker Compose
- Make

**Install uv**:
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Installing Development Dependencies

```bash
# Install all development dependencies (Python + Go tools)
make install-dev

# Install pre-commit hooks
make install-hooks
```

The `install-dev` target installs dependencies for local development.

**Note**: All Python commands are executed via `uv` to ensure consistent dependency management.

### Running Tests

```bash
# Run all unit tests (Go + Python)
make unit-tests

# Run unit tests for specific components
make unit-tests-sidecar    # Go sidecar unit tests only
make unit-tests-gateway    # Go gateway unit tests only
make unit-tests-runtime    # Python runtime unit tests only

# Run all integration tests (requires Docker compose)
make integration-tests

# Run specific integration test suites
make integration-tests-sidecar   # E2E: Sidecar ↔ Runtime via RabbitMQ
make integration-tests-gateway   # E2E: Gateway ↔ Actors via RabbitMQ

# Run all tests (unit + integration)
make test-all

# Clean up integration test Docker resources
make clean-integration
```

### Code Coverage

The project uses **octocov** for code coverage reporting - a fully open-source solution that runs in GitHub Actions without external services.

**Quick Coverage Check:**
```bash
# Run all tests with coverage and display summary (recommended)
make coverage

# Run coverage for specific components
make -C src/asya-sidecar coverage   # Sidecar (Go)
make -C src/asya-gateway coverage   # Gateway (Go)
make -C operator coverage           # Operator (Go)
make -C src/asya-runtime coverage   # Runtime (Python)
make -C src/asya-crew coverage    # System actors (Python)
```

The `make coverage` command:
- Runs all tests with coverage enabled
- Displays a clean summary for each component
- Prevents coverage output from getting lost in verbose test logs
- Generates HTML reports for detailed analysis

**Local Development:**
- Use `make coverage` to see coverage summaries
- Tests display coverage stats in the terminal
- No configuration needed

**CI/Pull Requests:**
- Coverage reports are automatically posted as PR comments
- Coverage history is tracked in the `gh-pages` branch
- Uses only `GITHUB_TOKEN` (no third-party API keys needed)

**Viewing detailed coverage reports:**
```bash
# After running 'make coverage', HTML reports are generated:
# - Python: open src/asya-runtime/htmlcov/index.html
# - Go: go tool cover -html=src/asya-sidecar/coverage.out
```

**Coverage files:**
- Go: `coverage.out`, `coverage-integration.out`
- Python: `coverage.xml` (Cobertura format), `htmlcov/` (HTML reports)
- All coverage files are ignored by git (see `.gitignore`)

### Building

```bash
# Build all components (Go sidecar + gateway)
make build

# Build only Go components
make build-go

# Build all Docker images
make build-images

# Load built images into Minikube
make load-minikube

# Build and load images into Minikube (one command)
make load-minikube-build
```

### Linting and Formatting

```bash
# Run all linters and formatters (automatically fixes issues when possible)
make lint

# Install pre-commit hooks (runs linters on git commit)
make install-hooks
```

### Integration Test Requirements

The integration tests require Docker to spin up:
- RabbitMQ for message queuing
- Actor runtime (Python) containers
- Actor sidecar (Go) containers
- Gateway (for gateway tests)

These tests validate the complete message flow through the system.

### Deployment Commands

```bash
# Deploy full stack to Minikube (requires Minikube running)
make deploy-minikube

# Port-forward Grafana to localhost:3000
make port-forward-grafana
```

### Other Utilities

```bash
# Clean build artifacts
make clean

# See all available commands
make help
```

## Making Changes

1. Create a feature branch from `main`
2. Make your changes
3. Run tests: `make test`
4. Run linters: `make lint`
5. Commit your changes (pre-commit hooks will run automatically)
6. Push and create a pull request
