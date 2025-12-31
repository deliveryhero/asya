.PHONY: test-unit cov-unit clean
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(subst $(PROJECT_ROOT)/,,$(CURDIR))
$(shell mkdir -p $(COVERAGE_DIR))

test-unit:
	uv run pytest ./tests -v
	@echo "[+] Success: asya-testing unit tests"

cov-unit:
	@echo "asya-testing (Python) coverage:"
	@uv run coverage report --data-file=$(COVERAGE_DIR)/cov.db --include="asya_testing/**/*.py"

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
