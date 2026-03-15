.PHONY: test test-one clean ensure-coverage-dir cov
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/component/flow-compiler)
COVERAGERC := $(PROJECT_ROOT)/.coveragerc
$(shell mkdir -p "$(COVERAGE_DIR)" 2>/dev/null)
UID := $(shell id -u)
export GID := $(shell id -g)

validate-env:
	@test -n "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR is empty" && exit 1)
	@test -n "$(COVERAGERC)" || (echo "[-] COVERAGERC is empty" && exit 1)
	@test -d "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR does not exist: $(COVERAGE_DIR)" && exit 1)

export ASYA_LOG_LEVEL ?= INFO
export PYTEST_OPTS ?= -v --cov --cov-report=term

test: clean validate-env ## Run flow compiler component tests
	@echo "[.] Running flow compiler component tests"
	$(MAKE) ensure-coverage-dir
	cd $(PROJECT_ROOT)/src/asya-lab && \
		COVERAGE_FILE=$(COVERAGE_DIR)/cov.db \
		uv run --group test \
		pytest $(PYTEST_OPTS) \
		--cov=asya_lab.flow \
		--cov-report=json:$(COVERAGE_DIR)/cov.json \
		../../testing/component/flow-compiler/tests/
	@test -f $(COVERAGE_DIR)/cov.json && echo "[+] Coverage JSON: $(COVERAGE_DIR)/cov.json" || echo "[-] Coverage not generated"
	@echo "[+] Success: Flow compiler component tests passed!"

test-one: test ## Alias for CI compatibility (no transport/profile config needed)

cov: ## Display component test coverage report
	@echo "Flow compiler (component) coverage:"
	@test -f $(COVERAGE_DIR)/cov.db && cd $(PROJECT_ROOT)/src/asya-lab && uv run --group test coverage report --data-file=$(COVERAGE_DIR)/cov.db || echo "[-] Coverage not generated"

clean: ## Clean coverage directory
	rm -rf $(COVERAGE_DIR)
	$(MAKE) ensure-coverage-dir

ensure-coverage-dir: ## Ensure coverage directory exists with correct ownership
	mkdir -p $(COVERAGE_DIR) && chown -R $(UID):$(GID) $(COVERAGE_DIR) || true
