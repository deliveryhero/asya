.PHONY: test clean down
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/component/state-proxy-s3kv)
$(shell mkdir -p "$(COVERAGE_DIR)" 2>/dev/null)

DOCKER_COMPOSE ?= docker compose
export DOCKER_BUILDKIT := 1
export BUILDKIT_PROGRESS ?= plain
export COMPOSE_ANSI ?= never
DOCKER_COMPOSE_UP_OPTS := --exit-code-from tester --build
export PYTEST_OPTS ?= -v

COMPOSE_PROJECT := comp-state-proxy-s3kv

test: clean ## Run state-proxy-s3kv component tests
	@echo "[.] Running state-proxy-s3kv component tests"
	$(DOCKER_COMPOSE) -f docker-compose.yml -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester
	$(MAKE) down
	@echo "[+] Success: state-proxy-s3kv component tests passed"

down: ## Stop and remove containers and volumes
	$(DOCKER_COMPOSE) -f docker-compose.yml -p $(COMPOSE_PROJECT) down -v --remove-orphans || true

clean: down ## Clean up coverage dir and containers
	rm -rf $(COVERAGE_DIR)
	mkdir -p $(COVERAGE_DIR)
