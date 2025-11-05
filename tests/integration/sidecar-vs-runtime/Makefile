.PHONY: test-integration clean-integration
# env var overloadable vars:
DOCKER_COMPOSE ?= docker compose
PYTEST_OPTS ?=
ASYA_LOG_LEVEL ?= INFO
# manually set vars:
DOCKER_COMPOSE_UP_OPTS := --build --abort-on-container-exit --exit-code-from tester tester

test-integration:
	$(MAKE) clean-integration
	PYTEST_OPTS="$(PYTEST_OPTS)" ASYA_LOG_LEVEL="$(ASYA_LOG_LEVEL)" $(DOCKER_COMPOSE) -p sc up $(DOCKER_COMPOSE_UP_OPTS)
	$(MAKE) clean-integration
	@echo "[+] Success: Sidecar vs Runtime integration tests"

clean-integration:
	$(DOCKER_COMPOSE) -p sc down -v --remove-orphans || true
	docker ps
