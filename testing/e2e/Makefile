.PHONY: help up test test-operator clean down trigger-tests port-forward-up port-forward-down diagnostics logs debug
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR))

UV_RUN_OPTS := --with $(PROJECT_ROOT)/src/asya-testing
PYTEST_WORKERS ?= auto
PYTEST_OPTS ?= -v -s -n $(PYTEST_WORKERS) --dist loadscope
export PYTEST_OPTS

# Validate PROFILE is set and valid (only when needed)
PROFILE_REQUIRED_TARGETS := up test trigger-tests test-operator down clean
ifneq ($(filter $(PROFILE_REQUIRED_TARGETS),$(MAKECMDGOALS)),)
  ifndef PROFILE
    $(error PROFILE is not set. Use: make <target> PROFILE=sqs-s3 or PROFILE=rabbitmq-minio)
  endif
  ifneq ($(filter-out sqs-s3 rabbitmq-minio,$(PROFILE)),)
    $(error Unknown PROFILE: $(PROFILE). Valid profiles: sqs-s3, rabbitmq-minio)
  endif
endif

ASYA_HANDLER_MODE ?= payload
ifdef PROFILE
  CLUSTER_NAME := asya-e2e-$(PROFILE)
endif

export CLUSTER_NAME
export PROFILE
export ASYA_HANDLER_MODE

up: ## Deploy E2E environment
	CLUSTER_NAME=$(CLUSTER_NAME) PROFILE=$(PROFILE) ./scripts/deploy.sh

test: ## Run complete E2E tests (deploy → port-forward-up → test both modes → port-forward-down → cleanup)
	$(MAKE) up
	$(MAKE) port-forward-up
	$(MAKE) trigger-tests ASYA_HANDLER_MODE=payload
	$(MAKE) trigger-tests ASYA_HANDLER_MODE=envelope
	$(MAKE) test-operator
	$(MAKE) port-forward-down
	$(MAKE) down

port-forward-up: ## Start port-forwards in background (idemportent operation)
	./scripts/port-forward.sh start

port-forward-down: ## Stop all port-forwards
	./scripts/port-forward.sh stop

trigger-tests: ## Only trigger tests, assuming that Kind cluster is already up (sets up port-forwarding if needed)
	@echo "Running E2E tests with profile=$(PROFILE) handler_mode=$(ASYA_HANDLER_MODE)..."
	@mkdir -p $(COVERAGE_DIR)
	$(MAKE) port-forward-up
	set -a && . ./profiles/.env.$(PROFILE) && set +a && \
		uv run $(UV_RUN_OPTS) pytest tests/ $(PYTEST_OPTS)
	@test -f $(COVERAGE_DIR)/cov-$(ASYA_HANDLER_MODE).json && echo "[+] Coverage JSON: $(COVERAGE_DIR)/cov-$(ASYA_HANDLER_MODE).json" || echo "[-] Coverage not generated"
	@echo "[+] Success: E2E tests with $(PROFILE) profile and $(ASYA_HANDLER_MODE) handler mode"
	$(MAKE) port-forward-down

test-operator: ## Run operator-specific E2E tests (shell scripts)
	@echo "[.] Running Operator E2E tests with profile=$(PROFILE)"
	$(MAKE) port-forward-up
	@for script in tests_operator/*.sh; do \
		echo "[.] Running $$script"; \
		PROJECT_ROOT=$(PROJECT_ROOT) PROFILE=$(PROFILE) SYSTEM_NAMESPACE=$(SYSTEM_NAMESPACE) bash "$$script" || exit 1; \
		echo "[+] $$script: PASSED"; \
		echo ""; \
	done
	@echo "[+] All Operator E2E tests: PASSED"
	$(MAKE) port-forward-down

cov: ## Display e2e test coverage report
	@echo "E2e coverage:"
	@uv run $(UV_RUN_OPTS) coverage report --data-file=$(COVERAGE_DIR)/cov.db


diagnostics: ## Run diagnostics on the current E2E environment
	./scripts/debug.sh diagnostics

logs: ## Show recent logs from all Asya components
	./scripts/debug.sh logs

down clean: ## Delete Kind cluster and cleanup
	kind delete cluster --name "$(CLUSTER_NAME)" || true
	rm -rf .coverage
	@echo "[+] Kind cluster '$(CLUSTER_NAME)' deleted"
