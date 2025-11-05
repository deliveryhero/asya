.PHONY: help deps fmt test build run clean

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

deps: ## Download and tidy Go dependencies
	go mod download
	go mod tidy

fmt: ## Format code with go fmt
	go fmt ./...

test-unit: ## Run unit tests only
	go test ./... -v

test-integration: ## Run integration tests
	go test -tags=integration ./tests/integration -v

test: test-unit test-integration ## Run all tests (unit + integration)

build: ## Build the gateway binary
	go build -o bin/gateway ./cmd/gateway

run: ## Run the gateway locally
	go run ./cmd/gateway

clean: ## Clean build artifacts
	rm -rf bin/
