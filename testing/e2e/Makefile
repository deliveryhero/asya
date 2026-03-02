.PHONY: help up test test-crossplane clean down trigger-tests diagnostics logs debug
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(subst $(PROJECT_ROOT)/,,$(CURDIR))

UV_RUN_OPTS := --with-editable $(PROJECT_ROOT)/src/asya-testing
PYTEST_WORKERS ?= auto
PYTEST_OPTS ?= -v -s -n $(PYTEST_WORKERS) --dist loadscope
COVERAGERC := $(PROJECT_ROOT)/.coveragerc
export PYTEST_OPTS
export COVERAGERC

# Validate PROFILE is set and valid (only when needed)
PROFILE_REQUIRED_TARGETS := up test trigger-tests test-crossplane down clean
ifneq ($(filter $(PROFILE_REQUIRED_TARGETS),$(MAKECMDGOALS)),)
  ifndef PROFILE
    $(error PROFILE is not set. Use: make <target> PROFILE=sqs-s3 or PROFILE=rabbitmq-minio)
  endif
  ifneq ($(filter-out sqs-s3 rabbitmq-minio,$(PROFILE)),)
    $(error Unknown PROFILE: $(PROFILE). Valid profiles: sqs-s3, rabbitmq-minio)
  endif
endif

ifdef PROFILE
  CLUSTER_NAME := asya-e2e-$(PROFILE)
endif

NAMESPACE := asya-e2e
SYSTEM_NAMESPACE := asya-system
REGISTRY_NAME := asya-e2e-registry

export SYSTEM_NAMESPACE
export NAMESPACE
export PROJECT_ROOT
export CLUSTER_NAME
export PROFILE

up: ## Deploy E2E environment
	./scripts/deploy.sh

test: ## Run complete E2E tests (deploy → test → cleanup)
	$(MAKE) up
	$(MAKE) trigger-tests
	$(MAKE) down

trigger-tests: ## Only trigger tests, assuming that Kind cluster is already up
	@echo "Running E2E tests with profile=$(PROFILE)..."
	@mkdir -p $(COVERAGE_DIR)
	set -a && . ./profiles/.env.$(PROFILE) && set +a && \
		uv run $(UV_RUN_OPTS) pytest tests/ $(PYTEST_OPTS) \
			--cov --cov-config=$(COVERAGERC) --cov-report=term \
			--cov-report=json:$(COVERAGE_DIR)/cov-$(PROFILE).json
	@test -f $(COVERAGE_DIR)/cov-$(PROFILE).json && echo "[+] Coverage JSON: $(COVERAGE_DIR)/cov-$(PROFILE).json" || echo "[-] Coverage not generated"
	@echo "[+] Success: E2E tests with $(PROFILE) profile"

test-crossplane: ## Run Crossplane + Injector E2E tests
	@echo "[.] Running Crossplane E2E tests with profile=$(PROFILE)"
	@mkdir -p $(COVERAGE_DIR)
	set -a && . ./profiles/.env.$(PROFILE) && set +a && \
		uv run $(UV_RUN_OPTS) pytest tests/test_crossplane_e2e.py $(PYTEST_OPTS) \
			--cov --cov-config=$(COVERAGERC) --cov-report=term \
			--cov-report=json:$(COVERAGE_DIR)/cov-$(PROFILE)-crossplane.json
	@echo "[+] All Crossplane E2E tests: PASSED"

cov: ## Display e2e test coverage report
	@echo "E2e coverage:"
	@for cov_file in $(COVERAGE_DIR)/cov-*.json; do \
		if [ -f "$$cov_file" ]; then \
			echo ""; \
			echo "Coverage from $$cov_file:"; \
			uv run $(UV_RUN_OPTS) coverage report --data-file=$$cov_file; \
		fi; \
	done


diagnostics: ## Run diagnostics on the current E2E environment
	./scripts/debug.sh diagnostics

logs: ## Show recent logs from all Asya components
	./scripts/debug.sh logs

down clean: ## Delete Kind cluster and cleanup
	kind delete cluster --name "$(CLUSTER_NAME)" || true
	docker rm -f "$(REGISTRY_NAME)" 2>/dev/null || true
	rm -rf .coverage
	@echo "[+] Kind cluster '$(CLUSTER_NAME)' and local registry deleted"
