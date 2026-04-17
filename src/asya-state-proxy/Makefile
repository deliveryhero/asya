.PHONY: test-unit lint

test-unit:
	uv run --project . --extra test --extra s3 --extra gcs --extra redis pytest tests/ -v
	$(MAKE) -C go test-unit

lint:
	uv run --project . ruff check . --fix
	uv run --project . ruff format .
	$(MAKE) -C go lint
