.PHONY: test test-one clean down help
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

DOCKER_COMPOSE ?= docker compose
export DOCKER_BUILDKIT := 1
export BUILDKIT_PROGRESS ?= plain
export COMPOSE_ANSI ?= never
COMPOSE_PROJECT := comp-transport
COMPOSE_FILES := -f docker-compose.yml

test: clean ## Run socket transport component tests
	$(MAKE) test-one

test-one: ## Run socket transport component tests (no clean)
	@echo "[.] Running socket transport component tests"
	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) up --exit-code-from tester --build
	$(MAKE) down
	@echo "[+] Success: Transport component tests passed!"

down: ## Stop and remove containers and volumes
	$(DOCKER_COMPOSE) $(COMPOSE_FILES) -p $(COMPOSE_PROJECT) down -v --remove-orphans || true

clean: down ## Remove containers and volumes
