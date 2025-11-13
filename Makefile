# Central Makefile chaining targets in other Makefiles
.PHONY: setup lint test test-unit test-component clean-component test-integration clean-integration test-e2e up-e2e clean-e2e diagnostics-e2e build build-go build-images manifests clean cov
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

GREEN_START := \033[32m
GREEN_END := \033[0m

# Tool versions (keep the format - it's grepped in action.yml)
GOLANGCI_LINT_VERSION := v1.62.2
GOIMPORTS_VERSION := v0.28.0

# =============================================================================
# Development
# =============================================================================

setup: ## Set up development environment (install deps, pre-commit hooks)
	@echo "[.] Setting up development environment..."
	@command -v uv >/dev/null 2>&1 || (echo "[-] uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" && exit 1)
	@command -v go >/dev/null 2>&1 || (echo "[-] Go not found. Install Go 1.23+" && exit 1)
	@echo "[+] Installing Python development tools..."
	uv pip install pre-commit
	@echo "[+] Installing Go linting tools..."
	@command -v goimports >/dev/null 2>&1 || go install golang.org/x/tools/cmd/goimports@$(GOIMPORTS_VERSION)
	@command -v golangci-lint >/dev/null 2>&1 || go install github.com/golangci/golangci-lint/cmd/golangci-lint@$(GOLANGCI_LINT_VERSION)
	@echo "[+] Installing pre-commit hooks..."
	uv run pre-commit install
	@echo "[+] Syncing Go dependencies..."
	cd src/asya-gateway && go mod download && go mod tidy
	cd src/asya-sidecar && go mod download && go mod tidy
	cd src/asya-operator && go mod download && go mod tidy
	@echo "[++] Setup complete! Ready for development."

setup-dev: setup ## Alias for setup (backwards compatibility)

install-dev: setup ## Alias for setup (backwards compatibility)

lint:
	uv run pre-commit run --show-diff-on-failure -a

# =============================================================================
# Unit + integration tests
# =============================================================================
test: test-unit test-integration ## Run all unit+integration tests
	@echo "$(GREEN_START)[+++] Success: All unit+integration tests completed successfully!$(GREEN_END)"

# =============================================================================
# Unit tests
# =============================================================================

test-unit: ## Run unit tests (go + python)
	$(MAKE) -C src/asya-sidecar test-unit
	$(MAKE) -C src/asya-gateway test-unit
	$(MAKE) -C src/asya-runtime test-unit
	$(MAKE) -C src/asya-crew test-unit
	$(MAKE) -C src/asya-operator test-unit
	@echo "$(GREEN_START)[++] Success: All unit tests completed successfully!$(GREEN_END)"

# =============================================================================
# Component tests (single component + lightweight mocks in docker-compose)
# =============================================================================

test-component: ## Run all component tests
	$(MAKE) -C testing/component test

clean-component: ## Clean component test Docker resources
	$(MAKE) -C testing/component clean

# =============================================================================
# Integration tests (multiple components in docker-compose)
# =============================================================================

test-integration: ## Run all integration tests
	$(MAKE) -C testing/integration test
	@echo "$(GREEN_START)[++] Success: All integration tests completed successfully!$(GREEN_END)"

clean-integration: ## Clean up integration test Docker resources
	$(MAKE) -C testing/integration clean
	docker ps

# =============================================================================
# End-to-end tests (in Kind)
# =============================================================================

test-e2e: ## Run complete E2E tests (deploy → port-forward-up → test → port-forward-down → cleanup, plus separate operator e2e tests)
	$(MAKE) -C testing/e2e test-complete-cycle
	@echo "$(GREEN_START)[++] Success: All e2e tests completed successfully!$(GREEN_END)"

clean-e2e: ## Delete Kind cluster and cleanup
	$(MAKE) -C testing/e2e clean

# =============================================================================
# Coverage
# =============================================================================

cov: ## Run all tests with coverage and display summary
	$(MAKE) -C src/asya-sidecar cov-unit
	$(MAKE) -C src/asya-gateway cov-unit
	$(MAKE) -C src/asya-operator cov-unit
	$(MAKE) -C src/asya-runtime cov-unit
	$(MAKE) -C src/asya-crew cov-unit
	$(MAKE) -C testing/integration cov
	$(MAKE) -C testing/component cov
	$(MAKE) -C testing/e2e cov-e2e

# =============================================================================
# Build
# =============================================================================

build-go: ## Build all Go components
	$(MAKE) -C src/asya-gateway build
	$(MAKE) -C src/asya-sidecar build
	$(MAKE) -C src/asya-operator build

build: build-go ## Build all components
	@echo "$(GREEN_START)[++] Success: All components built successfully!$(GREEN_END)"

manifests: ## Regenerate operator CRDs and manifests
	$(MAKE) -C src/asya-operator manifests
	@echo "$(GREEN_START)[+] Operator manifests regenerated (Helm chart uses symlink to src/asya-operator/config/crd/)$(GREEN_END)"

build-images: ## Build all Docker images for the framework
	./src/build-images.sh

clean: clean-integration clean-e2e ## Clean build artifacts
	$(MAKE) -C src/asya-crew clean
	$(MAKE) -C src/asya-sidecar clean
	$(MAKE) -C src/asya-runtime clean
	$(MAKE) -C src/asya-gateway clean
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "cov*.json" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name ".cov-db" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".coverage" -exec rm -rf {} + 2>/dev/null || true
