.PHONY: test-unit cov-unit clean build-ui build-widget lint-ui test-ui
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(subst $(PROJECT_ROOT)/,,$(CURDIR))
$(shell mkdir -p $(COVERAGE_DIR))

test-unit:
	COVERAGE_FILE=$(COVERAGE_DIR)/cov.db uv run --group test pytest ./tests
	uv run --group test coverage json --data-file=$(COVERAGE_DIR)/cov.db -o $(COVERAGE_DIR)/cov.json
	@test -f $(COVERAGE_DIR)/cov.json && echo "[+] Coverage JSON: $(COVERAGE_DIR)/cov.json" || echo "[-] Coverage not generated"
	@echo "[+] Success: asya-lab unit tests"

cov-unit:
	@echo "asya-lab (Python) coverage:"
	@uv run --group test coverage report --data-file=$(COVERAGE_DIR)/cov.db --include="asya_lab/**/*.py"

build-ui:
	cd ui && npm ci && npm run build
	@echo "[+] Success: @asya/ui build"

build-widget:
	cd ui && npm run build:widget
	@echo "[+] Success: widget bundle built"

lint-ui:
	cd ui && npm run lint && npm run typecheck
	@echo "[+] Success: @asya/ui lint + typecheck"

test-ui:
	cd ui && npm test
	@echo "[+] Success: @asya/ui tests"

clean:
	rm -rf __pycache__/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf $(COVERAGE_DIR)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	uv venv -c
	@echo "[+] Clean complete"
