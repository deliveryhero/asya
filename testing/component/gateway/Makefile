.PHONY: test test-one cov down clean
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/component/gateway)
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
DOCKER_COMPOSE_UP_OPTS := --exit-code-from tester-go
export ASYA_LOG_LEVEL ?= INFO
ASYA_TRANSPORT ?= sqs
export ASYA_TRANSPORT
export ASYA_STORAGE := minio
export ASYA_HANDLER_MODE := payload

COMPOSE_FILES := -f profiles/$(ASYA_TRANSPORT).yml
COMPOSE_PROJECT := comp-gateway-$(ASYA_TRANSPORT)

test: clean
	@echo "[.] Running gateway component tests"
	$(MAKE) test-one ASYA_TRANSPORT=sqs
	$(MAKE) test-one ASYA_TRANSPORT=rabbitmq


test-one: require-ASYA_TRANSPORT validate-env
	@echo "[.] Running gateway component tests with $(ASYA_TRANSPORT) transport"
	COVERAGE_DIR="$(COVERAGE_DIR)" COVERAGERC="$(COVERAGERC)" ASYA_TRANSPORT="$(ASYA_TRANSPORT)" ASYA_LOG_LEVEL="$(ASYA_LOG_LEVEL)" ASYA_STORAGE="$(ASYA_STORAGE)" ASYA_HANDLER_MODE="$(ASYA_HANDLER_MODE)" $(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester-go
	$(MAKE) down ASYA_TRANSPORT=$(ASYA_TRANSPORT)
	@test -f $(COVERAGE_DIR)/cov-$(ASYA_TRANSPORT).json && \
		echo "[+] Coverage: $(COVERAGE_DIR)/cov-$(ASYA_TRANSPORT).json" || \
		echo "[-] Coverage not generated"
	@echo "[+] Success: Gateway component tests passed with $(ASYA_TRANSPORT) transport"

debug: require-ASYA_TRANSPORT validate-env
	@echo "[.] Running gateway component tests with $(ASYA_TRANSPORT) transport (DEBUG MODE - all container logs)"
	COVERAGE_DIR="$(COVERAGE_DIR)" COVERAGERC="$(COVERAGERC)" ASYA_TRANSPORT="$(ASYA_TRANSPORT)" ASYA_LOG_LEVEL="DEBUG" ASYA_STORAGE="$(ASYA_STORAGE)" ASYA_HANDLER_MODE="$(ASYA_HANDLER_MODE)" $(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) up

cov:
	@echo "Gateway (component) coverage:"
	@ls -1 $(COVERAGE_DIR)/cov-*.json 2>/dev/null || echo "[-] Coverage not generated"

down: require-ASYA_TRANSPORT
	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) down -v --remove-orphans || true
	docker volume rm $(COMPOSE_PROJECT)_default 2>/dev/null || true

clean:
	$(MAKE) down ASYA_TRANSPORT=sqs || true
	$(MAKE) down ASYA_TRANSPORT=rabbitmq || true
	rm -rf $(COVERAGE_DIR)

require-%:
	@test -n "$($*)" || (echo "[-] $* not defined. Use: make <target> $*=..." && exit 1)
