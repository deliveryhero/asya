.PHONY: test-unit cov-unit build clean
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(subst $(PROJECT_ROOT)/,,$(CURDIR))
$(shell mkdir -p $(COVERAGE_DIR))
export UID := $(shell id -u)
export GID := $(shell id -g)

GOTEST_OPTS ?= -v

test-unit:
	go test -coverprofile=$(COVERAGE_DIR)/cov.out -covermode=set $(GOTEST_OPTS) ./...
	@test -f $(COVERAGE_DIR)/cov.out && echo "[+] Coverage: $(COVERAGE_DIR)/cov.out" || echo "[-] Coverage not generated"
	@echo "[+] Success: Sidecar unit tests"

cov-unit:
	@echo "Sidecar (unit) coverage:"
	@go tool cover -func=$(COVERAGE_DIR)/cov.out | tail -1

build:
	go build -o bin/sidecar ./cmd/sidecar

clean:
	rm -rf bin/
	rm -rf $(COVERAGE_DIR)
	go clean
