.PHONY: test test-one clean down ensure-coverage-dir
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/component/runtime)
COVERAGERC := $(PROJECT_ROOT)/.coveragerc
$(shell mkdir -p "$(COVERAGE_DIR)" 2>/dev/null)
UID := $(shell id -u)
export GID := $(shell id -g)

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
export PYTEST_OPTS ?= -v --cov --cov-report=term
ASYA_HANDLER_MODE ?= payload
export ASYA_HANDLER_MODE
COMPOSE_PROJECT := comp-runtime-$(ASYA_HANDLER_MODE)
COMPOSE_FILES := -f docker-compose.yml

test: clean ## Run runtime component tests with both handler modes
	$(MAKE) test-one ASYA_HANDLER_MODE=payload
	$(MAKE) test-one ASYA_HANDLER_MODE=envelope


test-one: validate-env ## Run runtime component tests with single handler mode
	@echo "[.] Running runtime component tests with $(ASYA_HANDLER_MODE) handler mode"
	$(MAKE) ensure-coverage-dir
	PYTEST_OPTS="$(PYTEST_OPTS)" ASYA_LOG_LEVEL="$(ASYA_LOG_LEVEL)" ASYA_HANDLER_MODE="$(ASYA_HANDLER_MODE)" $(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester
	$(MAKE) down ASYA_HANDLER_MODE=$(ASYA_HANDLER_MODE)
	@test -f $(COVERAGE_DIR)/cov-$(ASYA_HANDLER_MODE).json && echo "[+] Coverage JSON: $(COVERAGE_DIR)/cov-$(ASYA_HANDLER_MODE).json" || echo "[-] Coverage not generated"
	@echo "[+] Success: Runtime component tests passed with $(ASYA_HANDLER_MODE) handler mode!"

cov: ## Display component test coverage report
	@echo "Runtime (component) coverage:"
	@test -f $(COVERAGE_DIR)/cov.db && uv run --with-requirements requirements.txt coverage report --data-file=$(COVERAGE_DIR)/cov.db || echo "[-] Coverage not generated"

down: ## Stop and remove all containers and volumes
	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) down -v --remove-orphans || true
	docker volume rm $(COMPOSE_PROJECT)_sockets $(COMPOSE_PROJECT)_default 2>/dev/null || true

clean: down ## Clean coverage directory and recreate with correct ownership
	rm -rf $(COVERAGE_DIR)
	$(MAKE) ensure-coverage-dir

ensure-coverage-dir: ## Ensure coverage directory exists with correct ownership
	mkdir -p $(COVERAGE_DIR) && chown -R $(UID):$(GID) $(COVERAGE_DIR) || true
