.PHONY: test test-sidecar test-runtime test-gateway test-gateway-a2a test-gateway-mcp test-state-proxy clean help
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

GREEN_START := \033[32m
GREEN_END := \033[0m

test:
	$(MAKE) -C sidecar test
	$(MAKE) -C runtime test
	$(MAKE) -C gateway test
	$(MAKE) -C gateway-a2a test
	$(MAKE) -C gateway-mcp test
	$(MAKE) -C gateway-mcp test-auth
	$(MAKE) -C state-proxy test
	@echo "$(GREEN_START)[++] Success: All component tests passed!$(GREEN_END)"

cov:
	$(MAKE) -C sidecar cov
	$(MAKE) -C runtime cov
	$(MAKE) -C gateway cov
	$(MAKE) -C gateway-a2a cov
	$(MAKE) -C gateway-mcp cov
	$(MAKE) -C state-proxy cov

clean:
	$(MAKE) -C sidecar clean
	$(MAKE) -C runtime clean
	$(MAKE) -C gateway clean
	$(MAKE) -C gateway-a2a clean
	$(MAKE) -C gateway-mcp clean
	$(MAKE) -C state-proxy clean
