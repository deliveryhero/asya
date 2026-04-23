.PHONY: lint lint-fix compile compile-verify build test-e2e cluster-up cluster-down clean
MAKEFLAGS += --no-print-directory

REPO_ROOT := $(shell git rev-parse --show-toplevel)

CLUSTER_NAME ?= asya-samples-e2e
REGISTRY_NAME ?= asya-samples-registry
REGISTRY_PORT ?= 5111
NAMESPACE ?= asya-samples
SYSTEM_NAMESPACE ?= asya-system

CATEGORIES := control-flow compiler-sugar agentic resiliency text-improver

# =============================================================================
# Lint
# =============================================================================

lint:
	uvx ruff check src/
	uvx ruff format --check src/

lint-fix:
	uvx ruff check --fix src/
	uvx ruff format src/

# =============================================================================
# Compile
# =============================================================================

compile:
	@echo "[.] Compiling all flows..."
	@failed=0; \
	count=0; \
	for flow_file in src/*/flows/flow_*.py; do \
		[ -f "$$flow_file" ] || continue; \
		flow_name="$$(basename "$$flow_file" .py)"; \
		count=$$((count + 1)); \
		if PYTHONPATH="src:$${PYTHONPATH:-}" uv run --with "asya-lab @ file://$(REPO_ROOT)/src/asya-lab" asya compile "$$flow_name" -f "$$flow_file" 2>&1 | tail -1; then \
			: ; \
		else \
			echo "[-] FAILED: $$flow_file"; \
			failed=1; \
		fi; \
	done; \
	if [ $$failed -eq 1 ]; then \
		echo "[-] Some flows failed to compile"; \
		exit 1; \
	fi; \
	echo "[+] All $$count flows compiled"
	@$(MAKE) compile-verify

compile-verify:
	@echo "[.] Verifying compiled output..."
	@failed=0; \
	for flow_file in src/*/flows/flow_*.py; do \
		[ -f "$$flow_file" ] || continue; \
		flow_name="$$(basename "$$flow_file" .py)"; \
		if [ ! -f ".asya/flows/$$flow_name/routers.py" ]; then \
			echo "[-] Missing routers.py for $$flow_name"; \
			failed=1; \
		fi; \
		if [ ! -d ".asya/flows/$$flow_name/manifests/base" ] && [ ! -f ".asya/flows/$$flow_name/routers.py" ]; then \
			echo "[-] Missing manifests/base/ and routers.py for $$flow_name"; \
			failed=1; \
		fi; \
	done; \
	if [ $$failed -eq 1 ]; then \
		echo "[-] Verification failed"; \
		exit 1; \
	fi
	@echo "[+] All compiled output verified"

# =============================================================================
# Build
# =============================================================================

build:
	@for category in $(CATEGORIES); do \
		echo "[.] Building $$category..."; \
		skaffold build -f src/$$category/skaffold.yaml -q || exit 1; \
		echo "[+] Built $$category"; \
	done

# =============================================================================
# E2E
# =============================================================================

test-e2e: cluster-up
	@echo "[.] Deploying infrastructure..."
	bash testing/e2e/deploy.sh
	@echo "[.] Verifying deployment..."
	bash testing/e2e/verify.sh
	@echo "[+] E2E tests passed"

cluster-up:
	@if k3d cluster list 2>/dev/null | grep -q "$(CLUSTER_NAME)"; then \
		echo "[.] Cluster $(CLUSTER_NAME) already exists"; \
	else \
		echo "[.] Creating k3d cluster $(CLUSTER_NAME)..."; \
		k3d cluster create $(CLUSTER_NAME) \
			--registry-create $(REGISTRY_NAME):0.0.0.0:$(REGISTRY_PORT) \
			--wait; \
		echo "[+] Cluster created"; \
	fi

cluster-down:
	k3d cluster delete $(CLUSTER_NAME) 2>/dev/null || true
	@echo "[+] Cluster deleted"

# =============================================================================
# Clean
# =============================================================================

clean:
	rm -rf .asya/flows/*/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "[+] Clean complete"
