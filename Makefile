# Central Makefile chaining targets in other Makefiles
.PHONY: help install-dev install-hooks lint test-unit test-all test-integration test-integration-sidecar test-integration-gateway test-e2e clean-integration build build-go build-images clean kind-deploy kind-deploy-clean

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-25s %s\n", $$1, $$2}'

GREEN_START := \033[32m
GREEN_END := \033[0m

# =============================================================================
# Development
# =============================================================================

install-dev: ## Install development dependencies (Python + Go tools)
	@echo "Installing Python development dependencies..."
	@uv pip install -r requirements-dev.txt

install-hooks: ## Install pre-commit hooks
	@uv run pre-commit install

lint: ## Run all linters and formatters via pre-commit
	@uv run pre-commit run -a

# =============================================================================
# Testing
# =============================================================================

test-all: test-unit test-integration ## Run all tests including integration
	@echo "$(GREEN_START)[+++] Success:$(GREEN_END) All tests completed successfully!"

test-unit-sidecar: ## Run lightweight tests for asya-sidecar
	$(MAKE) -C src/asya-sidecar test-unit
	@echo "[+] Success: Sidecar Unit tests"

test-unit-gateway: ## Run lightweight tests for asya-gateway
	$(MAKE) -C src/asya-gateway test-unit
	@echo "[+] Success: Gateway Unit tests"

test-unit-runtime: ## Run lightweight tests for asya-runtime
	$(MAKE) -C src/asya-runtime test-unit
	@echo "[+] Success: Runtime Unit tests"

test-unit-actors: ## Run lightweight tests for asya-actors (happy-end, error-end)
	$(MAKE) -C src/asya-actors test-unit
	@echo "[+] Success: Actors Unit tests"

test-unit: test-unit-sidecar test-unit-gateway test-unit-runtime test-unit-actors ## Run lightweight tests (go + python)
	@echo "$(GREEN_START)[++] Success:$(GREEN_END) All lightweight tests completed successfully!"

test-integration: ## Run all integration tests
	$(MAKE) test-integration-sidecar
	$(MAKE) test-integration-gateway
	@echo "$(GREEN_START)[++] Success:$(GREEN_END) All integration tests completed successfully!"

test-integration-sidecar:  ## Run sidecar<->runtime integration tests with RabbitMQ (requires Docker)
	$(MAKE) -C src/asya-sidecar test-integration
	$(MAKE) -C tests/integration/sidecar-vs-runtime test-integration

test-integration-gateway: ## Run gateway<->actors integration tests with RabbitMQ (requires Docker)
	$(MAKE) -C src/asya-gateway test-integration
	$(MAKE) -C tests/integration/gateway-vs-actors test-integration

clean-integration: ## Clean up integration test Docker resources
	$(MAKE) -C tests/integration/sidecar-vs-runtime clean-integration
	$(MAKE) -C tests/integration/gateway-vs-actors clean-integration
	docker ps

# =============================================================================
# Building
# =============================================================================

build: build-go ## Build all components

build-go: ## Build Go sidecar
	cd src/asya-sidecar && make build

build-images: ## Build all Docker images for the framework
	./scripts/build-images.sh

clean: clean-integration ## Clean build artifacts
	cd src/asya-sidecar && make clean
	rm -rf .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

# =============================================================================
# E2E Tests (Kind)
# =============================================================================

e2e-deploy: ## Deploy E2E test environment to Kind (creates cluster, builds images, deploys)
	$(MAKE) -C tests/e2e deploy

e2e-test: ## Run E2E tests against Kind deployment (requires Kind cluster running)
	$(MAKE) -C tests/e2e test

e2e-clean: ## Delete Kind cluster and clean up E2E environment
	$(MAKE) -C tests/e2e clean
