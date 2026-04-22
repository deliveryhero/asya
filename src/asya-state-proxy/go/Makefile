.PHONY: build build-pg-kv build-s3-kv test test-unit lint clean

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(subst $(PROJECT_ROOT)/,,$(CURDIR))
$(shell mkdir -p $(COVERAGE_DIR))

build: build-pg-kv build-s3-kv ## Build all state-proxy Go binaries

build-pg-kv: ## Build pg-kv binary (CGO disabled, runs on alpine)
	CGO_ENABLED=0 go build -o bin/pg-kv ./cmd/pg-kv/

build-s3-kv: ## Build s3-kv binary (CGO required for go-duckdb)
	CGO_ENABLED=1 go build -o bin/s3-kv ./cmd/s3-kv/

test:
	CGO_ENABLED=1 go test -coverprofile=$(COVERAGE_DIR)/cov.out -covermode=set -v ./...
	@test -f $(COVERAGE_DIR)/cov.out && echo "[+] Coverage: $(COVERAGE_DIR)/cov.out" || echo "[-] Coverage not generated"
	@echo "[+] Success: state-proxy-go unit tests"

test-unit: test

lint:
	go vet ./...

clean:
	rm -rf bin/
	rm -rf $(COVERAGE_DIR)
	go clean
