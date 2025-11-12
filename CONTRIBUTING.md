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
make test-unit

# Run unit tests for specific components
make -C src/asya-sidecar test-unit    # Go sidecar unit tests only
make -C src/asya-gateway test-unit    # Go gateway unit tests only
make -C src/asya-runtime test-unit    # Python runtime unit tests only

# Run all integration tests (requires Docker Compose)
make test-integration

# Run specific integration test suites
make -C testing/integration/sidecar-runtime test   # Sidecar ↔ Runtime
make -C testing/integration/gateway-actors test    # Gateway ↔ Actors

# Run all tests (unit + integration)
make test

# Clean up integration test Docker resources
make clean-integration
```

### Code Coverage

The project uses **octocov** for code coverage reporting - a fully open-source solution that runs in GitHub Actions without external services.

**Quick Coverage Check:**
```bash
# Run all tests with coverage and display summary (recommended)
make cov

# Run coverage for specific components
make -C src/asya-sidecar cov-unit   # Sidecar (Go)
make -C src/asya-gateway cov-unit   # Gateway (Go)
make -C src/asya-operator cov-unit  # Operator (Go)
make -C src/asya-runtime cov-unit   # Runtime (Python)
make -C src/asya-crew cov-unit      # System actors (Python)
```

The `make cov` command:
- Runs all tests with coverage enabled
- Displays a clean summary for each component
- Prevents coverage output from getting lost in verbose test logs
- Generates HTML reports for detailed analysis

**Local Development:**
- Use `make cov` to see coverage summaries
- Tests display coverage stats in the terminal
- No configuration needed

**CI/Pull Requests:**
- Coverage reports are automatically posted as PR comments
- Coverage history is tracked in the `gh-pages` branch
- Uses only `GITHUB_TOKEN` (no third-party API keys needed)

**Viewing detailed coverage reports:**
```bash
# After running 'make cov', HTML reports are generated:
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

## Release Process

### Automated Release Workflow

Asya uses automated workflows for releases and changelog management:

1. **Draft Releases**: Release-drafter automatically maintains a draft release with categorized changelog based on merged PRs
2. **Docker Images**: When a release is published, Docker images are automatically built and pushed to GitHub Container Registry
3. **Changelog**: CHANGELOG.md is automatically updated via a pull request after release

### Creating a Release

1. **Review the draft release**:
   - Go to [Releases](https://github.com/deliveryhero/asya/releases)
   - Review the auto-generated draft release created by release-drafter
   - Edit the release notes if needed

2. **Publish the release**:
   - Click "Publish release"
   - This triggers the release workflow which:
     - Builds all Docker images (asya-operator, asya-gateway, asya-sidecar, asya-crew, asya-testing)
     - Pushes images to `ghcr.io/deliveryhero/asya-*:VERSION`
     - Tags images as `latest` (for non-prerelease versions)

3. **Docker Images**:
   - Images are published to GitHub Container Registry (ghcr.io)
   - Available at: `ghcr.io/deliveryhero/asya-<component>:<version>`
   - Latest stable version tagged as: `ghcr.io/deliveryhero/asya-<component>:latest`

4. **Changelog Update**:
   - After release publication, a PR is automatically created to update CHANGELOG.md
   - Review and merge the PR to keep the changelog in sync

### PR Labels for Release Notes

To help categorize changes in the release notes, use these labels on your PRs:

- `feature`, `enhancement` - New features
- `fix`, `bugfix`, `bug` - Bug fixes
- `documentation`, `docs` - Documentation updates
- `test`, `testing` - Test improvements
- `performance`, `optimization` - Performance improvements
- `ci`, `build`, `dependencies`, `chore` - Infrastructure changes
- `breaking`, `breaking-change` - Breaking changes (triggers major version bump)

Labels are automatically applied based on file paths, but you can add them manually for better categorization.

### Versioning

The project follows [Semantic Versioning](https://semver.org/):

- **Major** (X.0.0): Breaking changes (labels: `breaking`, `breaking-change`)
- **Minor** (0.X.0): New features (labels: `feature`, `enhancement`)
- **Patch** (0.0.X): Bug fixes and minor improvements (labels: `fix`, `bugfix`, `documentation`, `chore`)

Release-drafter automatically suggests the next version based on PR labels.
