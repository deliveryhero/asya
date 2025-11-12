.PHONY: test cov clean help
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/component/operator/transport_metrics)
COVERAGERC := $(PROJECT_ROOT)/.coveragerc
$(shell mkdir -p "$(COVERAGE_DIR)" 2>/dev/null)

# Validate required variables are set
validate-env:
	@test -n "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR is empty" && exit 1)
	@test -n "$(COVERAGERC)" || (echo "[-] COVERAGERC is empty" && exit 1)
	@test -d "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR does not exist: $(COVERAGE_DIR)" && exit 1)

DOCKER_COMPOSE ?= docker compose
export BUILDKIT_PROGRESS ?= plain
export COMPOSE_ANSI ?= never
DOCKER_COMPOSE_UP_OPTS := --exit-code-from tester

test: clean validate-env
	@echo "[.] Running transport metrics component tests"
	$(DOCKER_COMPOSE) up $(DOCKER_COMPOSE_UP_OPTS)
	@$(DOCKER_COMPOSE) down -v --remove-orphans || true
	@test -f $(COVERAGE_DIR)/cov.out && echo "[+] Coverage: $(COVERAGE_DIR)/cov.out" || echo "[-] Coverage not generated"
	@echo "[+] Success: Transport metrics component tests"

cov:
	@echo "Transport metrics (component) coverage:"
	@test -f $(COVERAGE_DIR)/cov.out && go tool cover -func=$(COVERAGE_DIR)/cov.out | tail -1 || echo "  [-] Coverage not generated"

clean:
	@echo "[.] Cleaning up"
	$(DOCKER_COMPOSE) down -v --remove-orphans || true
	docker volume rm transport_metrics_go-cache 2>/dev/null || true

help:
	@echo "Transport Metrics Component Tests"
	@echo ""
	@echo "Targets:"
	@echo "  test      Run all transport metrics tests in Docker"
	@echo "  cov       Coverage (not applicable for Go integration tests)"
	@echo "  clean     Clean up Docker resources"
