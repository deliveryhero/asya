.PHONY: help deps fmt test build build-release clean run-sqs run-rabbitmq docker-build docker-run

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

deps: ## Download and tidy Go dependencies
	go mod download
	go mod tidy

fmt: ## Format code with go fmt
	go fmt ./...

test-unit: ## Run unit tests only
	go test -v $(shell go list ./... | grep -v /tests/integration)

test-integration: ## Run integration tests
	go test -tags=integration ./tests/integration -v

test: test-unit test-integration ## Run all tests (unit + integration)

build: ## Build the sidecar binary
	go build -o bin/sidecar ./cmd/sidecar

build-release: ## Build optimized release binary
	CGO_ENABLED=0 go build -ldflags="-s -w" -o bin/sidecar ./cmd/sidecar

clean: ## Clean build artifacts
	rm -rf bin/
	go clean

run-sqs: ## Run with SQS configuration
	@echo "Running with SQS transport..."
	@export TRANSPORT_TYPE=sqs && \
	export ASYA_QUEUE_NAME=test-queue && \
	export QUEUE_BASE_URL=https://sqs.us-east-1.amazonaws.com/123456789012 && \
	./bin/sidecar

run-rabbitmq: ## Run with RabbitMQ configuration
	@echo "Running with RabbitMQ transport..."
	@export TRANSPORT_TYPE=rabbitmq && \
	export ASYA_QUEUE_NAME=test-queue && \
	./bin/sidecar

docker-build: ## Build Docker image
	docker build -t asya-sidecar:latest .

docker-run: ## Run Docker container
	docker run --rm \
		-v /tmp/sockets:/tmp/sockets \
		-e TRANSPORT_TYPE=sqs \
		-e ASYA_QUEUE_NAME=test-queue \
		-e QUEUE_BASE_URL=https://sqs.us-east-1.amazonaws.com/123456789012 \
		asya-sidecar:latest
