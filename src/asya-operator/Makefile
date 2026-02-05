.PHONY: generate manifests controller-gen test-unit test-integration test-e2e test cov-unit cov-integration cov-e2e build run install uninstall deploy undeploy clean setup-envtest
MAKEFLAGS += --no-print-directory
.EXPORT_ALL_VARIABLES:

PROJECT_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(CURDIR)/../..)
COVERAGE_DIR := $(PROJECT_ROOT)/.coverage/$(subst $(PROJECT_ROOT)/,,$(CURDIR))
$(shell mkdir -p $(COVERAGE_DIR))
export UID := $(shell id -u)
export GID := $(shell id -g)

LOCALBIN := $(CURDIR)/bin
$(shell mkdir -p $(LOCALBIN))

IMG ?= asya-operator:latest
GOTEST_OPTS ?=
ENVTEST_K8S_VERSION := 1.29.0
CONTROLLER_GEN_VERSION := v0.14.0

controller-gen:
	@test -s $(LOCALBIN)/controller-gen && test -x $(LOCALBIN)/controller-gen || \
	GOBIN=$(LOCALBIN) go install sigs.k8s.io/controller-tools/cmd/controller-gen@$(CONTROLLER_GEN_VERSION)

manifests: controller-gen
	$(LOCALBIN)/controller-gen crd paths="./..." output:crd:artifacts:config=config/crd

generate: controller-gen
	$(LOCALBIN)/controller-gen object:headerFile=hack/boilerplate.go.txt paths="./..."

setup-envtest:
	@command -v setup-envtest >/dev/null 2>&1 || go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest
	@setup-envtest use $(ENVTEST_K8S_VERSION) -p path

test test-unit:
	go test -coverprofile=$(COVERAGE_DIR)/cov.out -covermode=set $(GOTEST_OPTS) ./...
	@test -f $(COVERAGE_DIR)/cov.out && echo "[+] Coverage: $(COVERAGE_DIR)/cov.out" || echo "[-] Coverage not generated"
	@echo "[+] Success: Operator unit tests"

cov cov-unit:
	@echo "Operator (unit) coverage:"
	@go tool cover -func=$(COVERAGE_DIR)/cov.out | tail -1

build:
	go build -o bin/manager cmd/main.go

run:
	go run cmd/main.go

install:
	kubectl apply -f config/crd/

uninstall:
	kubectl delete -f config/crd/

deploy:
	cd config/manager && kubectl apply -k .

undeploy:
	cd config/manager && kubectl delete -k .

clean:
	rm -rf bin/
	rm -rf $(COVERAGE_DIR)
	go clean
