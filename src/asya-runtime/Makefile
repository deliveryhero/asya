.PHONY: test-unit cov-unit clean
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR))
$(shell mkdir -p $(COVERAGE_DIR))
UV_RUN_OPTS := --with-requirements tests/requirements.txt

test-unit:
	COVERAGE_FILE=$(COVERAGE_DIR)/cov.db uv run $(UV_RUN_OPTS) pytest ./tests
	uv run $(UV_RUN_OPTS) coverage json --data-file=$(COVERAGE_DIR)/cov.db -o $(COVERAGE_DIR)/cov.json
	@test -f $(COVERAGE_DIR)/cov.json && echo "[+] Coverage JSON: $(COVERAGE_DIR)/cov.json" || echo "[-] Coverage not generated"
	@echo "[+] Success: Runtime unit tests"

cov-unit:
	@echo "Runtime (Python) coverage:"
	@uv run $(UV_RUN_OPTS) coverage report --data-file=$(COVERAGE_DIR)/cov.db --include="asya_runtime.py"

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
