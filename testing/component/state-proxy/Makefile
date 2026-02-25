.PHONY: test test-one clean down ensure-coverage-dir
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/component/state-proxy)
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

CONNECTOR_PROFILE ?= s3-lww
COMPOSE_PROJECT := comp-state-proxy-$(CONNECTOR_PROFILE)
COMPOSE_ENV_FILES := --env-file profiles/.env.shared --env-file profiles/.env.$(CONNECTOR_PROFILE)
COMPOSE_FILES := $(COMPOSE_ENV_FILES) -f profiles/$(CONNECTOR_PROFILE).yml

test: clean ## Run all state-proxy component test profiles
	$(MAKE) test-one CONNECTOR_PROFILE=s3-lww
	$(MAKE) test-one CONNECTOR_PROFILE=s3-passthrough
	$(MAKE) test-one CONNECTOR_PROFILE=s3-cas
	$(MAKE) test-one CONNECTOR_PROFILE=redis-cas

test-one: validate-env ## Run state-proxy component tests for a single profile
	@test -n "$(CONNECTOR_PROFILE)" || (echo "[-] CONNECTOR_PROFILE not set" && exit 1)
	@echo "[.] Running state-proxy component tests with '$(CONNECTOR_PROFILE)' profile"
	$(MAKE) ensure-coverage-dir
	PYTEST_OPTS="$(PYTEST_OPTS)" $(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester
	$(MAKE) down
	@test -f $(COVERAGE_DIR)/cov-$(CONNECTOR_PROFILE).json \
		&& echo "[+] Coverage: $(COVERAGE_DIR)/cov-$(CONNECTOR_PROFILE).json" \
		|| echo "[!] No coverage JSON found"
	@echo "[+] Success: State-proxy component tests passed ($(CONNECTOR_PROFILE))!"

validate-env:
	@test -n "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR is empty" && exit 1)
	@test -n "$(COVERAGERC)" || (echo "[-] COVERAGERC is empty" && exit 1)
	@test -d "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR does not exist: $(COVERAGE_DIR)" && exit 1)

cov: ## Display component test coverage report
	@echo "State-proxy (component) coverage:"
	@ls -1 $(COVERAGE_DIR)/cov-*.json 2>/dev/null || echo "[-] No coverage files"

down: ## Stop and remove all containers and volumes
	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) down -v --remove-orphans || true
	docker volume rm $(COMPOSE_PROJECT)_state-sockets $(COMPOSE_PROJECT)_runtime-sockets $(COMPOSE_PROJECT)_default 2>/dev/null || true

clean: down ## Clean coverage directory and recreate with correct ownership
	rm -rf $(COVERAGE_DIR)
	$(MAKE) ensure-coverage-dir

ensure-coverage-dir: ## Ensure coverage directory exists with correct ownership
	mkdir -p $(COVERAGE_DIR) && chown -R $(UID):$(GID) $(COVERAGE_DIR) || true
