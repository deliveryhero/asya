# Discover all actor directories (directories with requirements.txt)
ACTORS := $(patsubst %/requirements.txt,%,$(wildcard */requirements.txt))

.PHONY: help test clean

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

list-actors: ## List all actors in current dir
	@echo $(ACTORS)

test-unit: ## Run all actor unit tests
	uv run --with-requirements=requirements.txt,requirements-dev.txt pytest tests/ -v
	@echo "[++] Success: All actor tests completed successfully!"

clean: ## Clean test artifacts
	@echo "[*] Cleaning test artifacts..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "[+] Clean complete"
