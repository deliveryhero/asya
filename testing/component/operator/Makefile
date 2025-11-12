.PHONY: test cov clean help
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

GREEN_START := \033[32m
GREEN_END := \033[0m

test:
	@$(MAKE) -C transport_metrics test
	@$(MAKE) -C runtime_configmap test
	@echo "$(GREEN_START)[++] Success: All operator component tests passed!$(GREEN_END)"

cov:
	@$(MAKE) -C transport_metrics cov
	@$(MAKE) -C runtime_configmap cov

clean:
	@$(MAKE) -C transport_metrics clean
	@$(MAKE) -C runtime_configmap clean

help:
	@echo "Operator Component Tests"
	@echo ""
	@echo "Targets:"
	@echo "  test      Run all operator component tests"
	@echo "  cov       Display coverage (if available)"
	@echo "  clean     Clean up test resources"
