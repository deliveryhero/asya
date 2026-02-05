.PHONY: test clean cov
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/integration/sidecar)
COVERAGERC := $(PROJECT_ROOT)/.coveragerc
$(shell mkdir -p "$(COVERAGE_DIR)" 2>/dev/null)

# Validate required variables are set
validate-env:
	@test -n "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR is empty" && exit 1)
	@test -n "$(COVERAGERC)" || (echo "[-] COVERAGERC is empty" && exit 1)
	@test -d "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR does not exist: $(COVERAGE_DIR)" && exit 1)

GOTEST_OPTS ?= -v

test: validate-env
	@echo "[.] Running sidecar integration tests"
	go test $(GOTEST_OPTS) -coverprofile=$(COVERAGE_DIR)/cov.out -covermode=set
	@test -f $(COVERAGE_DIR)/cov.out && echo "[+] Coverage: $(COVERAGE_DIR)/cov.out" || echo "[-] Coverage not generated"
	@echo "[+] Success: Sidecar socket integration tests"

cov:
	@echo "Sidecar (Go socket integration) coverage:"
	go tool cover -func=$(COVERAGE_DIR)/cov.out | tail -1

clean:
	rm -rf sidecar.test
	rm -rf $(COVERAGE_DIR)
