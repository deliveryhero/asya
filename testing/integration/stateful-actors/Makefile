.PHONY: test test-one cov down clean ensure-coverage-dir validate-env
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/integration/stateful-actors)
COVERAGERC := $(PROJECT_ROOT)/.coveragerc
$(shell mkdir -p "$(COVERAGE_DIR)" 2>/dev/null)
UID := $(shell id -u)
export GID := $(shell id -g)

DOCKER_COMPOSE ?= docker compose
export DOCKER_BUILDKIT := 1
export BUILDKIT_PROGRESS ?= plain
export COMPOSE_ANSI ?= never
DOCKER_COMPOSE_UP_OPTS := --exit-code-from tester --build
export PYTEST_OPTS ?= -v --cov --cov-report=term

COMPOSE_PROJECT := int-stateful-actors
COMPOSE_FILES := -f profiles/rabbitmq.yml

test: clean test-one ## Run stateful actors integration tests

test-one: validate-env ## Run tests
	@echo "[.] Running stateful actors integration tests"
	$(MAKE) ensure-coverage-dir
	PYTEST_OPTS="$(PYTEST_OPTS)" $(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester
	$(MAKE) down
	@echo "[+] Success: Stateful actors integration tests passed!"

validate-env:
	@test -n "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR is empty" && exit 1)
	@test -n "$(COVERAGERC)" || (echo "[-] COVERAGERC is empty" && exit 1)
	@test -d "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR does not exist: $(COVERAGE_DIR)" && exit 1)

cov: ## Display coverage report
	@echo "Stateful actors (integration) coverage:"
	@ls -1 $(COVERAGE_DIR)/cov-*.json 2>/dev/null || echo "[-] No coverage files"

down: ## Stop and remove all containers and volumes
	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) down -v --remove-orphans || true

clean: down ## Clean coverage directory
	rm -rf $(COVERAGE_DIR)
	$(MAKE) ensure-coverage-dir

ensure-coverage-dir:
	mkdir -p $(COVERAGE_DIR) && chown -R $(UID):$(GID) $(COVERAGE_DIR) || true
