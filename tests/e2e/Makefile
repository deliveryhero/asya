.PHONY: deploy clean test-e2e

CLUSTER_NAME := asya-kind

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

deploy: ## Deploy full stack to Kind
	CLUSTER_NAME=$(CLUSTER_NAME) ./scripts/deploy.sh

clean: ## Delete Kind cluster
	kind delete cluster --name "$(CLUSTER_NAME)"

test-e2e: ## Run E2E tests
	CLUSTER_NAME=$(CLUSTER_NAME) ./scripts/test-e2e.sh
