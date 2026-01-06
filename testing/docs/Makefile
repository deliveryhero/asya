.PHONY: help test test-quickstart clean
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(subst $(PROJECT_ROOT)/,,$(CURDIR))

UV_RUN_OPTS := --with-editable $(PROJECT_ROOT)/src/asya-testing
PYTEST_OPTS ?= -v --log-cli-level=INFO -s
COVERAGERC := $(PROJECT_ROOT)/.coveragerc

export PYTEST_OPTS
export COVERAGERC
export PROJECT_ROOT
export COVERAGE_DIR

help:
	@echo "Documentation Tests"
	@echo ""
	@echo "Available targets:"
	@echo "  test              - Run all documentation tests"
	@echo "  test-quickstart   - Run only quickstart README test"
	@echo "  clean             - Remove test artifacts and Kind clusters"
	@echo ""
	@echo "Example usage:"
	@echo "  make test                              # Run all docs tests"
	@echo "  make test-quickstart                   # Run quickstart test only"
	@echo "  make test PYTEST_OPTS='-v -x'          # Run with custom pytest options"
	@echo ""
	@echo "Note: These tests run independently of e2e infrastructure"
	@echo "      and create their own Kind clusters."

test:
	@echo "Running documentation tests..."
	uv run $(UV_RUN_OPTS) pytest tests/ $(PYTEST_OPTS) \
		--cov --cov-config=$(COVERAGERC) --cov-report=term \
		--cov-report=json:$(COVERAGE_DIR)/cov.json

test-quickstart:
	@echo "Running quickstart README test..."
	uv run $(UV_RUN_OPTS) pytest tests/test_quickstart_readme.py $(PYTEST_OPTS) \
		--cov --cov-config=$(COVERAGERC) --cov-report=term \
		--cov-report=json:$(COVERAGE_DIR)/cov-quickstart.json

clean:
	@echo "[.] Cleaning up docs test artifacts..."
	@kind delete cluster --name asya-local 2>/dev/null || true
	@rm -rf .pytest_cache
	@rm -rf __pycache__
	@rm -rf tests/__pycache__
	@rm -rf $(COVERAGE_DIR)
	@echo "[+] Cleanup complete"
