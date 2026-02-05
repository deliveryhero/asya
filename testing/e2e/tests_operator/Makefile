.PHONY: test
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

TEST_SCRIPTS := $(wildcard *.sh)

test: ## Run operator scenario tests (requires running K8s cluster)
	@echo "[.] Running operator scenario tests"
	@for script in $(sort $(TEST_SCRIPTS)); do \
		echo "[.] Running $$script..."; \
		bash $$script || exit 1; \
	done
	@echo "[+] Success: All operator scenario tests passed"
