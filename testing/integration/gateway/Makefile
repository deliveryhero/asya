.PHONY: test clean cov
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/integration/gateway)
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
GOTEST_OPTS ?= -v
COMPOSE_PROJECT := int-gateway

test: clean validate-env
	@echo "[.] Running gateway integration tests"
	$(DOCKER_COMPOSE) -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester
	@test -f $(COVERAGE_DIR)/cov.out && echo "[+] Coverage: $(COVERAGE_DIR)/cov.out" || echo "[-] Coverage not generated"
	@echo "[+] Success: Gateway integration tests"


cov:
	@echo "Gateway (integration) coverage:"
	@test -f $(COVERAGE_DIR)/cov.out && \
		go tool cover -func=$(COVERAGE_DIR)/cov.out | tail -1 || \
		echo "  [-] Coverage not generated"

clean down:
	$(DOCKER_COMPOSE) -p $(COMPOSE_PROJECT) down -v --remove-orphans || true
	$(DOCKER_COMPOSE) -p $(COMPOSE_PROJECT)-test down -v --remove-orphans || true
	docker volume rm gw_default gw-test_default 2>/dev/null || true
