.PHONY: test-unit cov-unit build clean
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(subst $(PROJECT_ROOT)/,,$(CURDIR))
export UID := $(shell id -u)
export GID := $(shell id -g)

GOTEST_OPTS ?= -v

test-unit:
	@mkdir -p $(COVERAGE_DIR)
	go test -coverprofile=$(COVERAGE_DIR)/cov.out -covermode=set $(GOTEST_OPTS) ./...
	@test -f $(COVERAGE_DIR)/cov.out && echo "[+] Coverage: $(COVERAGE_DIR)/cov.out" || echo "[-] Coverage not generated"
	@echo "[+] Success: function-asya-overlays unit tests"

cov-unit:
	@echo "function-asya-overlays (unit) coverage:"
	@go tool cover -func=$(COVERAGE_DIR)/cov.out | tail -1

build:
	CGO_ENABLED=0 go build -o bin/function .

clean:
	rm -rf bin/
	rm -rf $(COVERAGE_DIR)
	go clean
