.PHONY: test-unit cov-unit clean
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(subst $(PROJECT_ROOT)/,,$(CURDIR))
$(shell mkdir -p $(COVERAGE_DIR))
UV_RUN_OPTS := --with-requirements requirements.txt

test-unit:
	@echo "[+] Success: Lab unit tests (no tests yet)"

cov-unit:
	@echo "Lab (Python) coverage: N/A (no tests yet)"

clean:
	rm -rf .pytest_cache/
	rm -rf $(COVERAGE_DIR)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "[+] Clean complete"
