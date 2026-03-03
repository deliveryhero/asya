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
DOCKER_COMPOSE_UP_OPTS := --exit-code-from tester --build
export ASYA_LOG_LEVEL ?= INFO
ASYA_TRANSPORT ?= rabbitmq
export ASYA_TRANSPORT

PYTEST_OPTS ?= -v -s
export PYTEST_OPTS

COMPOSE_PROJECT := int-sidecar-runtime-$(ASYA_TRANSPORT)

test: clean test-rabbitmq test-sqs test-pubsub

test-rabbitmq:
	@echo "[.] Running RabbitMQ transport tests"
	$(MAKE) test-one ASYA_TRANSPORT=rabbitmq

test-sqs:
	@echo "[.] Running SQS transport tests"
	$(MAKE) test-one ASYA_TRANSPORT=sqs

test-pubsub:
	@echo "[.] Running Pub/Sub transport tests"
	$(MAKE) test-one ASYA_TRANSPORT=pubsub


test-one: require-ASYA_TRANSPORT validate-env
	@echo "[.] Running integration tests with '$(ASYA_TRANSPORT)' transport"
	$(DOCKER_COMPOSE) -f profiles/$(ASYA_TRANSPORT).yml -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester
	$(MAKE) down-one
	$(MAKE) cov-one
	@echo "[+] Success: $(ASYA_TRANSPORT) transport tests passed"

cov:
	$(MAKE) cov-one

cov-one: require-ASYA_TRANSPORT
	@echo "Sidecar-Runtime coverage:"
	@test -f $(COVERAGE_DIR)/cov-$(ASYA_TRANSPORT).json && \
		echo "  $(COVERAGE_DIR)/cov-$(ASYA_TRANSPORT).json" || \
		echo "  [-] Coverage not generated"

down:
	$(MAKE) down-one ASYA_TRANSPORT=rabbitmq || true
	$(MAKE) down-one ASYA_TRANSPORT=sqs || true
	$(MAKE) down-one ASYA_TRANSPORT=pubsub || true

down-one: require-ASYA_TRANSPORT
	$(DOCKER_COMPOSE) -f profiles/$(ASYA_TRANSPORT).yml -p $(COMPOSE_PROJECT) down -v --remove-orphans || true
	docker volume rm $(COMPOSE_PROJECT)_sockets $(COMPOSE_PROJECT)_default 2>/dev/null || true

clean:
	$(MAKE) clean-one ASYA_TRANSPORT=rabbitmq || true
	$(MAKE) clean-one ASYA_TRANSPORT=sqs || true
	$(MAKE) clean-one ASYA_TRANSPORT=pubsub || true
	rm -rf $(COVERAGE_DIR)

clean-one: require-ASYA_TRANSPORT
	$(MAKE) down-one ASYA_TRANSPORT=$(ASYA_TRANSPORT)

require-%:
	@test -n "$($*)" || (echo "[-] $* not defined. Use: make <target> $*=..." && exit 1)
