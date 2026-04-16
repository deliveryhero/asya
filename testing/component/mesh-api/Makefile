.PHONY: test test-one clean down
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR))
$(shell mkdir -p "$(COVERAGE_DIR)" 2>/dev/null)

DOCKER_COMPOSE ?= docker compose
export DOCKER_BUILDKIT := 1
export BUILDKIT_PROGRESS ?= plain
export COMPOSE_ANSI ?= never
DOCKER_COMPOSE_UP_OPTS := --exit-code-from tester-go --build
export ASYA_LOG_LEVEL ?= INFO
ASYA_TRANSPORT ?= sqs
export ASYA_TRANSPORT

COMPOSE_FILES := -f profiles/$(ASYA_TRANSPORT).yml
COMPOSE_PROJECT := comp-mesh-api-$(ASYA_TRANSPORT)

test: clean
	@echo "[.] Running mesh-api component tests"
	$(MAKE) test-one ASYA_TRANSPORT=sqs

test-one: require-ASYA_TRANSPORT
	@echo "[.] Running mesh-api component tests with $(ASYA_TRANSPORT) transport"
	COVERAGE_DIR="$(COVERAGE_DIR)" $(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester-go
	$(MAKE) down ASYA_TRANSPORT=$(ASYA_TRANSPORT)
	@echo "[+] Success: Mesh-API component tests passed"

down: require-ASYA_TRANSPORT
	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) down -v --remove-orphans || true

clean:
	$(MAKE) down ASYA_TRANSPORT=sqs || true
	rm -rf $(COVERAGE_DIR)

require-%:
	@test -n "$($*)" || (echo "[-] $* not defined" && exit 1)
