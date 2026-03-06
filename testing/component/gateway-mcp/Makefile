.PHONY: test test-auth cov clean down ensure-coverage-dir
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/component/gateway-mcp)
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
DOCKER_COMPOSE_UP_OPTS := --exit-code-from tester --build
export ASYA_LOG_LEVEL ?= INFO
export PYTEST_OPTS ?= -v --cov --cov-report=term
export PROTOCOL_VERSION ?= 2024-11-05

COMPOSE_PROJECT := comp-gateway-mcp
COMPOSE_FILES := -f docker-compose.yml
COMPOSE_AUTH_FILES := -f docker-compose.auth.yml

export MCP_API_KEY ?= test-mcp-secret-key

test: clean validate-env ## Run MCP protocol compliance tests (no auth)
	@echo "[.] Running MCP protocol compliance tests"
	$(MAKE) ensure-coverage-dir
	PYTEST_OPTS="$(PYTEST_OPTS)" ASYA_LOG_LEVEL="$(ASYA_LOG_LEVEL)" PROTOCOL_VERSION="$(PROTOCOL_VERSION)" $(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) up $(DOCKER_COMPOSE_UP_OPTS) tester
	$(MAKE) down
	@test -f $(COVERAGE_DIR)/cov.json && echo "[+] Coverage JSON: $(COVERAGE_DIR)/cov.json" || echo "[-] Coverage not generated"
	@echo "[+] Success: MCP compliance tests passed!"

test-auth: clean validate-env ## Run MCP API key authentication tests (Phase 2)
	@echo "[.] Running MCP auth tests with API key: $(MCP_API_KEY)"
	$(MAKE) ensure-coverage-dir
	MCP_API_KEY="$(MCP_API_KEY)" PYTEST_OPTS="$(PYTEST_OPTS)" ASYA_LOG_LEVEL="$(ASYA_LOG_LEVEL)" $(DOCKER_COMPOSE) $(COMPOSE_AUTH_FILES) -p $(COMPOSE_PROJECT)-auth up $(DOCKER_COMPOSE_UP_OPTS) tester
	$(DOCKER_COMPOSE) $(COMPOSE_AUTH_FILES) -p $(COMPOSE_PROJECT)-auth down -v --remove-orphans || true
	@test -f $(COVERAGE_DIR)/cov.json && echo "[+] Coverage JSON: $(COVERAGE_DIR)/cov.json" || echo "[-] Coverage not generated"
	@echo "[+] Success: MCP auth tests passed!"

cov: ## Display component test coverage report
	@echo "Gateway MCP (component) coverage:"
	@test -f $(COVERAGE_DIR)/cov.db && uv run --with-requirements requirements.txt coverage report --data-file=$(COVERAGE_DIR)/cov.db || echo "[-] Coverage not generated"

down: ## Stop and remove all containers and volumes
	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) down -v --remove-orphans || true
	$(DOCKER_COMPOSE) $(COMPOSE_AUTH_FILES) -p $(COMPOSE_PROJECT)-auth down -v --remove-orphans || true

clean: down ## Clean coverage directory and recreate with correct ownership
	rm -rf $(COVERAGE_DIR)
	$(MAKE) ensure-coverage-dir

ensure-coverage-dir: ## Ensure coverage directory exists with correct ownership
	mkdir -p $(COVERAGE_DIR) && chown -R $(UID):$(GID) $(COVERAGE_DIR) || true
