.PHONY: help deps lint test test-cov clean

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

deps: ## Install Python dependencies (requires uv)
	uv pip install -r ../requirements-dev.txt
	uv pip install -e .

lint: ## Run linters
	pre-commit run -a .

test-unit: ## Run tests with pytest
	uv run pytest tests/ -v

test-cov: ## Run tests with coverage report
	uv run pytest tests/ -v --cov=. --cov-report=term-missing --cov-report=html

clean: ## Clean Python cache and test artifacts
	rm -rf __pycache__/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
