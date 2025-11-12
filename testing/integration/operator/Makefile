.PHONY: test clean cov setup-envtest
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(shell realpath --relative-to=$(PROJECT_ROOT) $(CURDIR) 2>/dev/null || echo testing/integration/operator)
COVERAGERC := $(PROJECT_ROOT)/.coveragerc
$(shell mkdir -p "$(COVERAGE_DIR)" 2>/dev/null)

# Validate required variables are set
validate-env:
	@test -n "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR is empty" && exit 1)
	@test -n "$(COVERAGERC)" || (echo "[-] COVERAGERC is empty" && exit 1)
	@test -d "$(COVERAGE_DIR)" || (echo "[-] COVERAGE_DIR does not exist: $(COVERAGE_DIR)" && exit 1)

GOTEST_OPTS ?= -v
ENVTEST_K8S_VERSION := 1.29.0

setup-envtest:
	@command -v setup-envtest >/dev/null 2>&1 || go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest

test: setup-envtest validate-env
	@echo "[.] Running operator integration tests"
	KUBEBUILDER_ASSETS="$$(setup-envtest use $(ENVTEST_K8S_VERSION) -p path)" \
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
