.PHONY: test clean cov setup-envtest
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(subst $(PROJECT_ROOT)/,,$(CURDIR))
COVERAGERC := $(PROJECT_ROOT)/.coveragerc
$(shell mkdir -p "$(COVERAGE_DIR)" 2>/dev/null)

# Validate required variables are set
validate-env:
	@test -n "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR is empty" && exit 1)
	@test -n "$(COVERAGERC)" || (echo "[-] COVERAGERC is empty" && exit 1)
	@test -d "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR does not exist: $(COVERAGE_DIR)" && exit 1)

GOTEST_OPTS ?= -v
ENVTEST_K8S_VERSION := 1.29.0
GOPATH := $(shell go env GOPATH)
SETUP_ENVTEST := $(GOPATH)/bin/setup-envtest

setup-envtest:
	@test -x "$(SETUP_ENVTEST)" || go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest

test: setup-envtest validate-env
	@echo "[.] Running operator integration tests"
	KUBEBUILDER_ASSETS="$$($(SETUP_ENVTEST) use $(ENVTEST_K8S_VERSION) -p path)" \
		go test -coverprofile=$(COVERAGE_DIR)/cov.out \
		-covermode=set -coverpkg=github.com/asya/operator/internal/controller,github.com/asya/operator/api/... \
		$(GOTEST_OPTS) -tags=integration ./...
	@test -f $(COVERAGE_DIR)/cov.out && echo "[+] Coverage: $(COVERAGE_DIR)/cov.out" || echo "[-] Coverage not generated"
	@echo "[+] Success: Operator integration tests"

cov:
	@echo "Operator (integration) coverage:"
	go tool cover -func=$(COVERAGE_DIR)/cov.out | tail -1

clean:
	rm -rf $(COVERAGE_DIR)
