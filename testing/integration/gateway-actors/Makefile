.PHONY: test test-one cov cov-one down down-one clean clean-one
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/integration/gateway-actors)
COVERAGERC := $(PROJECT_ROOT)/.coveragerc
$(shell mkdir -p "$(COVERAGE_DIR)" 2>/dev/null)

# Validate required variables are set
validate-env:
	@test -n "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR is empty" && exit 1)
	@test -n "$(COVERAGERC)" || (echo "[-] COVERAGERC is empty" && exit 1)
	@test -d "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR does not exist: $(COVERAGE_DIR)" && exit 1)

DOCKER_COMPOSE ?= docker compose
export DOCKER_BUILDKIT := 1
export BUILDKIT_PROGRESS ?= plain
export COMPOSE_ANSI ?= never
DOCKER_COMPOSE_UP_OPTS := --build --exit-code-from tester
export ASYA_LOG_LEVEL ?= INFO
ASYA_HANDLER_MODE ?= payload
export ASYA_HANDLER_MODE
ASYA_TRANSPORT ?= sqs
export ASYA_TRANSPORT
ASYA_STORAGE ?= minio
export ASYA_STORAGE

PYTEST_OPTS ?= -v -s
export PYTEST_OPTS

COMPOSE_FILES := -f profiles/$(ASYA_TRANSPORT)-$(ASYA_STORAGE).yml
COMPOSE_PROJECT := int-gateway-actors-$(ASYA_HANDLER_MODE)-$(ASYA_TRANSPORT)-$(ASYA_STORAGE)

test: clean test-open test-aws

test-open:
	@echo "[.] Running open stack tests (RabbitMQ + MinIO)"
	$(MAKE) test-one ASYA_HANDLER_MODE=payload ASYA_TRANSPORT=rabbitmq ASYA_STORAGE=minio
	$(MAKE) test-one ASYA_HANDLER_MODE=envelope ASYA_TRANSPORT=rabbitmq ASYA_STORAGE=minio

test-aws:
	@echo "[.] Running AWS stack tests (SQS + S3)"
	$(MAKE) test-one ASYA_HANDLER_MODE=payload ASYA_TRANSPORT=sqs ASYA_STORAGE=s3
	$(MAKE) test-one ASYA_HANDLER_MODE=envelope ASYA_TRANSPORT=sqs ASYA_STORAGE=s3


test-one: require-ASYA_HANDLER_MODE validate-env
	@echo "[.] Running integration tests for '$(ASYA_HANDLER_MODE)' mode with '$(ASYA_TRANSPORT)' transport and '$(ASYA_STORAGE)' storage"
	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester
	$(MAKE) down-one ASYA_HANDLER_MODE=$(ASYA_HANDLER_MODE)
	$(MAKE) cov-one ASYA_HANDLER_MODE=$(ASYA_HANDLER_MODE)
	@echo "[+] Success: $(ASYA_HANDLER_MODE)-$(ASYA_TRANSPORT)-$(ASYA_STORAGE) mode tests passed"

cov:
	$(MAKE) cov-one ASYA_HANDLER_MODE=payload
	$(MAKE) cov-one ASYA_HANDLER_MODE=envelope

cov-one: require-ASYA_HANDLER_MODE
	@echo "Gateway-Actors $(ASYA_HANDLER_MODE) mode coverage:"
	@test -f $(COVERAGE_DIR)/cov-$(ASYA_HANDLER_MODE)-$(ASYA_TRANSPORT)-$(ASYA_STORAGE).json && \
		echo "  $(COVERAGE_DIR)/cov-$(ASYA_HANDLER_MODE)-$(ASYA_TRANSPORT)-$(ASYA_STORAGE).json" || \
		echo "  [-] Coverage not generated"

down:
	$(MAKE) down-one ASYA_HANDLER_MODE=payload || true
	$(MAKE) down-one ASYA_HANDLER_MODE=envelope || true

down-one: require-ASYA_HANDLER_MODE
	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) down -v --remove-orphans || true
	docker volume rm $(COMPOSE_PROJECT)_sockets $(COMPOSE_PROJECT)_default 2>/dev/null || true

clean:
	$(MAKE) clean-one ASYA_HANDLER_MODE=payload || true
	$(MAKE) clean-one ASYA_HANDLER_MODE=envelope || true
	rm -rf $(COVERAGE_DIR)

clean-one: require-ASYA_HANDLER_MODE
	$(MAKE) down-one ASYA_HANDLER_MODE=$(ASYA_HANDLER_MODE)

require-%:
	@test -n "$($*)" || (echo "[-] $* not defined. Use: make <target> $*=..." && exit 1)
