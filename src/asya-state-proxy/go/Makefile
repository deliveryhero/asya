.PHONY: build test lint clean

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(subst $(PROJECT_ROOT)/,,$(CURDIR))
$(shell mkdir -p $(COVERAGE_DIR))

build:
	go build -o bin/pg-kv ./cmd/pg-kv/

test:
	go test -coverprofile=$(COVERAGE_DIR)/cov.out -covermode=set -v ./...
	@test -f $(COVERAGE_DIR)/cov.out && echo "[+] Coverage: $(COVERAGE_DIR)/cov.out" || echo "[-] Coverage not generated"
	@echo "[+] Success: pg-kv unit tests"

test-unit: test

lint:
	go vet ./...

clean:
	rm -rf bin/
	rm -rf $(COVERAGE_DIR)
	go clean
