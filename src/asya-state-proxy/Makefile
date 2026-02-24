.PHONY: test-unit lint

test-unit:
	uv run --project . --extra test --extra s3 pytest tests/ -v

lint:
	uv run --project . ruff check . --fix
	uv run --project . ruff format .
