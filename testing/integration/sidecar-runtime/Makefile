.PHONY: test test-one cov cov-one down down-one clean clean-one
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/integration/sidecar-runtime)
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
DOCKER_COMPOSE_UP_OPTS := --exit-code-from tester
export ASYA_LOG_LEVEL ?= INFO
ASYA_HANDLER_MODE ?= payload
export ASYA_HANDLER_MODE
ASYA_TRANSPORT ?= rabbitmq
export ASYA_TRANSPORT

PYTEST_OPTS ?= -v -s
export PYTEST_OPTS

COMPOSE_PROJECT := int-sidecar-runtime-$(ASYA_HANDLER_MODE)-$(ASYA_TRANSPORT)

test: clean test-rabbitmq test-sqs

test-rabbitmq:
	@echo "[.] Running RabbitMQ transport tests"
	$(MAKE) test-one ASYA_HANDLER_MODE=payload ASYA_TRANSPORT=rabbitmq
	$(MAKE) test-one ASYA_HANDLER_MODE=envelope ASYA_TRANSPORT=rabbitmq

test-sqs:
	@echo "[.] Running SQS transport tests"
	$(MAKE) test-one ASYA_HANDLER_MODE=payload ASYA_TRANSPORT=sqs
	$(MAKE) test-one ASYA_HANDLER_MODE=envelope ASYA_TRANSPORT=sqs


test-one: require-ASYA_HANDLER_MODE validate-env
	@echo "[.] Running integration tests for '$(ASYA_HANDLER_MODE)' mode with '$(ASYA_TRANSPORT)' transport"
	$(DOCKER_COMPOSE) -f profiles/$(ASYA_TRANSPORT).yml -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester
	$(MAKE) down-one ASYA_HANDLER_MODE=$(ASYA_HANDLER_MODE)
	$(MAKE) cov-one ASYA_HANDLER_MODE=$(ASYA_HANDLER_MODE)
	@echo "[+] Success: $(ASYA_HANDLER_MODE)-$(ASYA_TRANSPORT) mode tests passed"

cov:
	$(MAKE) cov-one ASYA_HANDLER_MODE=payload
	$(MAKE) cov-one ASYA_HANDLER_MODE=envelope

cov-one: require-ASYA_HANDLER_MODE
	@echo "Sidecar-Runtime $(ASYA_HANDLER_MODE) mode coverage:"
	@test -f $(COVERAGE_DIR)/cov-$(ASYA_HANDLER_MODE)-$(ASYA_TRANSPORT).json && \
		echo "  $(COVERAGE_DIR)/cov-$(ASYA_HANDLER_MODE)-$(ASYA_TRANSPORT).json" || \
		echo "  [-] Coverage not generated"

down:
	$(MAKE) down-one ASYA_HANDLER_MODE=payload || true
	$(MAKE) down-one ASYA_HANDLER_MODE=envelope || true

down-one: require-ASYA_HANDLER_MODE
	$(DOCKER_COMPOSE) -f profiles/$(ASYA_TRANSPORT).yml -p $(COMPOSE_PROJECT) down -v --remove-orphans || true
	docker volume rm $(COMPOSE_PROJECT)_sockets $(COMPOSE_PROJECT)_default 2>/dev/null || true

clean:
	$(MAKE) clean-one ASYA_HANDLER_MODE=payload || true
	$(MAKE) clean-one ASYA_HANDLER_MODE=envelope || true
	rm -rf $(COVERAGE_DIR)

clean-one: require-ASYA_HANDLER_MODE
	$(MAKE) down-one ASYA_HANDLER_MODE=$(ASYA_HANDLER_MODE)

require-%:
	@test -n "$($*)" || (echo "[-] $* not defined. Use: make <target> $*=..." && exit 1)
