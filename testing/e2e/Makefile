.PHONY: help up test test-operator clean down trigger-tests port-forward-up port-forward-down diagnostics logs debug
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR))

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
NAMESPACE := asya-e2e
SYSTEM_NAMESPACE := asya-system

# Set profile-specific variables
ifdef PROFILE
  CLUSTER_NAME := asya-e2e-$(PROFILE)

  ifeq ($(PROFILE),sqs-s3)
    ASYA_TRANSPORT := sqs
    ASYA_STORAGE := s3
    QUEUE_ENDPOINT := http://localhost:4566
    STORAGE_ENDPOINT := http://localhost:4567
    S3_ACCESS_KEY := test
    S3_SECRET_KEY := test
  else ifeq ($(PROFILE),rabbitmq-minio)
    ASYA_TRANSPORT := rabbitmq
    ASYA_STORAGE := minio
    QUEUE_ENDPOINT := amqp://guest:guest@localhost:5672
    RABBITMQ_MGMT_URL := http://localhost:15672
    RABBITMQ_USER := guest
    RABBITMQ_PASS := guest
    STORAGE_ENDPOINT := http://localhost:9000
    S3_ACCESS_KEY := minioadmin
    S3_SECRET_KEY := minioadmin
  endif
endif

export CLUSTER_NAME
export NAMESPACE
export SYSTEM_NAMESPACE
export PROFILE
export ASYA_HANDLER_MODE
export ASYA_TRANSPORT
export ASYA_STORAGE

UV_RUN_OPTS := --with-requirements=$(PROJECT_ROOT)/src/asya-testing/requirements.txt
PYTEST_WORKERS ?= auto
PYTEST_OPTS ?= -v -s -n $(PYTEST_WORKERS) --dist loadscope
export PYTEST_OPTS

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
	PYTHONPATH=$(PROJECT_ROOT)/src/asya-testing:$(CURDIR)/..:$$PYTHONPATH \
		ASYA_GATEWAY_URL=http://localhost:8080 \
		ASYA_HANDLER_MODE=$(ASYA_HANDLER_MODE) \
		ASYA_TRANSPORT=$(ASYA_TRANSPORT) \
		ASYA_STORAGE=$(ASYA_STORAGE) \
		ASYA_LOG_LEVEL=$${ASYA_LOG_LEVEL:-INFO} \
		ASYA_E2E_DIAGNOSTICS=true \
		ASYA_S3_ENDPOINT=$(STORAGE_ENDPOINT) \
		ASYA_S3_REGION=us-east-1 \
		ASYA_S3_BUCKET=asya-results \
		ASYA_S3_ACCESS_KEY=$(S3_ACCESS_KEY) \
		ASYA_S3_SECRET_KEY=$(S3_SECRET_KEY) \
		ASYA_SQS_ENDPOINT=$(QUEUE_ENDPOINT) \
		RABBITMQ_URL=$(QUEUE_ENDPOINT) \
		RABBITMQ_MGMT_URL=$(RABBITMQ_MGMT_URL) \
		RABBITMQ_USER=$(RABBITMQ_USER) \
		RABBITMQ_PASS=$(RABBITMQ_PASS) \
		ASYA_RESULTS_BUCKET=asya-results \
		ASYA_ERRORS_BUCKET=asya-errors \
		NAMESPACE=$(NAMESPACE) \
		SYSTEM_NAMESPACE=$(SYSTEM_NAMESPACE) \
		AWS_ACCESS_KEY_ID=$(S3_ACCESS_KEY) \
		AWS_SECRET_ACCESS_KEY=$(S3_SECRET_KEY) \
		AWS_ENDPOINT_URL=$(QUEUE_ENDPOINT) \
		AWS_DEFAULT_REGION=us-east-1 \
		uv run $(UV_RUN_OPTS) \
		pytest tests/ $(PYTEST_OPTS)
	@test -f $(COVERAGE_DIR)/cov-$(ASYA_HANDLER_MODE).json && echo "[+] Coverage JSON: $(COVERAGE_DIR)/cov-$(ASYA_HANDLER_MODE).json" || echo "[-] Coverage not generated"
	@echo "[+] Success: E2E tests with $(PROFILE) profile and $(ASYA_HANDLER_MODE) handler mode"
	$(MAKE) port-forward-down

test-operator: ## Run operator-specific E2E tests (shell scripts)
	@echo "[.] Running Operator E2E tests with transport=$(ASYA_TRANSPORT)"
	$(MAKE) port-forward-up
	@for script in tests_operator/*.sh; do \
		echo "[.] Running $$script"; \
		env -u NAMESPACE SYSTEM_NAMESPACE=$(SYSTEM_NAMESPACE) ASYA_TRANSPORT=$(ASYA_TRANSPORT) bash "$$script" || exit 1; \
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
