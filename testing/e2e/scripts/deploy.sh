#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHARTS_DIR="$SCRIPT_DIR/../charts"
REGISTRY="${REGISTRY:-ghcr.io/deliveryhero}"

# Set image prefix based on registry
if [[ -n "$REGISTRY" ]]; then
  IMAGE_PREFIX="${REGISTRY}/"
else
  IMAGE_PREFIX=""
fi

# Detect CPU cores for parallel operations
if command -v nproc > /dev/null 2>&1; then
  NCPU=$(nproc)
elif command -v sysctl > /dev/null 2>&1; then
  NCPU=$(sysctl -n hw.ncpu)
else
  NCPU=4
fi
CONCURRENCY="${CONCURRENCY:-$NCPU}"

# Parse arguments
RECREATE_CLUSTER=false
if [[ "${1:-}" == "--recreate" ]]; then
  RECREATE_CLUSTER=true
fi

# Validate profile (Crossplane deploy only supports sqs-s3)
case "$PROFILE" in
  sqs-s3) ;;
  rabbitmq-minio)
    echo "[!] Profile rabbitmq-minio is not supported by Crossplane deploy."
    echo "    Use deploy_old.sh for rabbitmq-minio profile."
    exit 1
    ;;
  *)
    echo "[!] Unknown profile: $PROFILE"
    echo "    Valid profiles: sqs-s3"
    exit 1
    ;;
esac

CLUSTER_NAME="${CLUSTER_NAME:-asya-e2e-${PROFILE}}"
SYSTEM_NAMESPACE="${SYSTEM_NAMESPACE:-asya-system}"
NAMESPACE="${NAMESPACE:-asya-e2e}"

export HELMFILE_LOG_LEVEL="${HELMFILE_LOG_LEVEL:-error}"

echo "=== Asya Kind E2E Deployment Script (Crossplane) ==="
echo "Root directory: $ROOT_DIR"
echo "Charts directory: $CHARTS_DIR"
echo "Profile: $PROFILE"
echo "Cluster name: $CLUSTER_NAME"
echo "Namespace: $NAMESPACE (system: $SYSTEM_NAMESPACE)"
echo "Concurrency: $CONCURRENCY (CPUs: $NCPU)"
echo

# Check prerequisites
echo "[.] Checking prerequisites..."
command -v kind > /dev/null 2>&1 || {
  echo "Error: kind is not installed"
  exit 1
}
command -v kubectl > /dev/null 2>&1 || {
  echo "Error: kubectl is not installed"
  exit 1
}
command -v helm > /dev/null 2>&1 || {
  echo "Error: helm is not installed"
  exit 1
}
command -v helmfile > /dev/null 2>&1 || {
  echo "Error: helmfile is not installed"
  exit 1
}
command -v docker > /dev/null 2>&1 || {
  echo "Error: docker is not installed"
  exit 1
}
echo "[+] All prerequisites installed"
echo

# Phase 1: Create Kind cluster and build images in parallel
echo "[.] Phase 1: Setting up cluster and building components..."
time {
  # Start cluster creation
  CLUSTER_PID=""
  if kind get clusters 2> /dev/null | grep -q "^${CLUSTER_NAME}$"; then
    if [ "$RECREATE_CLUSTER" = true ]; then
      echo "[.] Deleting existing cluster..."
      kind delete cluster --name "$CLUSTER_NAME"
      kind create cluster --name "$CLUSTER_NAME" --config "$SCRIPT_DIR/../kind-config.yaml" &
      CLUSTER_PID=$!
    else
      echo "[!] Cluster '$CLUSTER_NAME' already exists, using existing cluster"
      echo "    (Use --recreate flag to delete and recreate)"
      kubectl config use-context "kind-${CLUSTER_NAME}"
    fi
  else
    echo "[.] Creating Kind cluster..."
    kind create cluster --name "$CLUSTER_NAME" --config "$SCRIPT_DIR/../kind-config.yaml" &
    CLUSTER_PID=$!
  fi

  # Build framework images (no operator needed)
  echo "[.] Building Docker images (gateway, sidecar, crew, testing)..."
  "$ROOT_DIR/src/build-images.sh" asya-gateway asya-sidecar asya-crew asya-testing &
  BUILD_PID=$!

  # Build injector image separately (not in build-images.sh registry)
  echo "[.] Building asya-injector image..."
  docker build -t "${IMAGE_PREFIX}asya-injector:latest" "$ROOT_DIR/src/asya-injector/" > /dev/null 2>&1 &
  INJECTOR_BUILD_PID=$!

  # Wait for image builds
  if ! wait "$BUILD_PID"; then
    echo "[-] Docker image build failed"
    exit 1
  fi
  echo "[+] Framework Docker images built"

  if ! wait "$INJECTOR_BUILD_PID"; then
    echo "[-] Injector image build failed"
    exit 1
  fi
  echo "[+] Injector image built"

  # Wait for cluster creation
  if [ -n "$CLUSTER_PID" ]; then
    if ! wait "$CLUSTER_PID"; then
      echo "[-] Kind cluster creation failed"
      exit 1
    fi
    kubectl config use-context "kind-${CLUSTER_NAME}"
    echo "[+] Kind cluster ready (context: kind-${CLUSTER_NAME})"
  fi
}
echo

# Phase 2: Install cluster-level infrastructure (cert-manager + Crossplane core)
echo "[.] Phase 2: Installing cluster-level infrastructure..."
time {
  echo "[.] Installing cert-manager..."
  kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.5/cert-manager.yaml > /dev/null 2>&1

  echo "[.] Installing Crossplane core..."
  helm repo add crossplane-stable https://charts.crossplane.io/stable --force-update > /dev/null 2>&1
  helm repo update crossplane-stable > /dev/null 2>&1
  helm upgrade --install crossplane crossplane-stable/crossplane \
    --namespace crossplane-system --create-namespace \
    --wait --timeout 120s > /dev/null 2>&1

  echo "[.] Waiting for cert-manager webhooks..."
  kubectl wait --for=condition=available deployment/cert-manager-webhook \
    -n cert-manager --timeout=120s > /dev/null 2>&1

  echo "[.] Waiting for Crossplane pods..."
  kubectl wait --for=condition=available deployment/crossplane \
    -n crossplane-system --timeout=120s > /dev/null 2>&1

  echo "[+] cert-manager and Crossplane core installed"
}
echo

# Phase 3: Load images into Kind cluster
echo "[.] Phase 3: Loading images into Kind cluster..."
time {
  IMAGES_TO_LOAD=(
    "asya-gateway:latest"
    "asya-sidecar:latest"
    "asya-crew:latest"
    "asya-testing:latest"
    "asya-injector:latest"
  )

  LOAD_PIDS=()
  for img in "${IMAGES_TO_LOAD[@]}"; do
    kind load docker-image "${IMAGE_PREFIX}$img" --name "$CLUSTER_NAME" &
    LOAD_PIDS+=($!)
  done

  # Wait for all loads to complete
  LOAD_FAILED=false
  for pid in "${LOAD_PIDS[@]}"; do
    if ! wait "$pid"; then
      LOAD_FAILED=true
    fi
  done

  if [ "$LOAD_FAILED" = true ]; then
    echo "[-] Failed to load one or more images into Kind cluster"
    exit 1
  fi

  echo "[+] Images loaded into Kind cluster"
}
echo

# Phase 4: Create prerequisite secrets
echo "[.] Phase 4: Creating prerequisite secrets..."
time {
  # Create namespaces if they don't exist
  kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
  kubectl create namespace "$SYSTEM_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1

  # AWS credentials for Crossplane provider (credentials file format)
  kubectl create secret generic aws-creds \
    -n crossplane-system \
    --from-literal=credentials="[default]
aws_access_key_id = test
aws_secret_access_key = test
" \
    --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
  echo "[+] Created aws-creds secret in crossplane-system"

  # AWS credentials for KEDA TriggerAuthentication (key/value format)
  kubectl create secret generic aws-creds \
    -n "$NAMESPACE" \
    --from-literal=AWS_ACCESS_KEY_ID=test \
    --from-literal=AWS_SECRET_ACCESS_KEY=test \
    --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
  echo "[+] Created aws-creds secret in $NAMESPACE"

  # sqs-secret in asya-system is created by the SQS Helm chart (testing/e2e/charts/sqs/)
  # Do NOT create it here — Helm requires ownership metadata on managed resources
}
echo

# Phase 5: Deploy infrastructure layer with Helmfile
echo "[.] Phase 5: Deploying infrastructure layer..."
time {
  cd "$CHARTS_DIR"
  if ! helmfile -f helmfile.yaml.gotmpl -e "$PROFILE" sync --concurrency "$CONCURRENCY" --selector 'layer=infra'; then
    echo "[-] Infrastructure deployment failed! Gathering diagnostics..."
    echo ""
    echo "=== Pod Status ==="
    kubectl get pods -n "$NAMESPACE" -o wide || true
    kubectl get pods -n "$SYSTEM_NAMESPACE" -o wide || true
    kubectl get pods -n crossplane-system -o wide || true
    kubectl get pods -n keda -o wide || true
    echo ""
    echo "=== Gateway Pod Events ==="
    kubectl get events -n "$NAMESPACE" --field-selector involvedObject.kind=Pod --sort-by='.lastTimestamp' | grep -i gateway || true
    echo ""
    echo "=== Gateway Pod Details ==="
    kubectl describe pod -n "$NAMESPACE" -l app.kubernetes.io/name=asya-gateway || true
    echo ""
    echo "=== Gateway Current Logs ==="
    kubectl logs -n "$NAMESPACE" -l app.kubernetes.io/name=asya-gateway --tail=100 --all-containers=true || true
    echo ""
    echo "=== Crossplane Provider Logs ==="
    kubectl logs -n crossplane-system -l pkg.crossplane.io/revision --tail=50 --all-containers=true || true
    echo ""
    echo "=== Injector Logs ==="
    kubectl logs -n "$SYSTEM_NAMESPACE" -l app.kubernetes.io/name=asya-injector --tail=50 || true
    echo ""
    echo "=== Migration Job Logs ==="
    kubectl logs -n "$NAMESPACE" -l app.kubernetes.io/component=migration --tail=50 || true
    exit 1
  fi
  echo "[+] Infrastructure layer deployed"
}
echo

# Phase 6: Wait for Crossplane providers to become healthy
echo "[.] Phase 6: Waiting for Crossplane providers to become healthy..."
time {
  echo "[.] Waiting for Crossplane providers..."
  if ! kubectl wait --for=condition=healthy providers.pkg.crossplane.io --all --timeout=300s 2> /dev/null; then
    echo "[!] Warning: Some Crossplane providers may not be healthy"
    kubectl get providers.pkg.crossplane.io || true
  else
    echo "[+] All Crossplane providers healthy"
  fi

  echo "[.] Waiting for Crossplane functions..."
  if ! kubectl wait --for=condition=healthy functions.pkg.crossplane.io --all --timeout=300s 2> /dev/null; then
    echo "[!] Warning: Some Crossplane functions may not be healthy"
    kubectl get functions.pkg.crossplane.io || true
  else
    echo "[+] All Crossplane functions healthy"
  fi
}
echo

# Phase 6b: Install ProviderConfigs (CRDs now available after providers are healthy)
echo "[.] Phase 6b: Installing Crossplane ProviderConfigs..."
time {
  cd "$CHARTS_DIR"
  helm upgrade asya-crossplane ../../../deploy/helm-charts/asya-crossplane \
    -n asya-system --reuse-values --set providerConfigs.install=true \
    --wait --timeout 120s > /dev/null 2>&1
  echo "[+] ProviderConfigs installed"
}
echo

# Phase 7: Deploy application layer with Helmfile (test actors + system actors)
echo "[.] Phase 7: Deploying application layer (actors)..."
time {
  cd "$CHARTS_DIR"
  if ! helmfile -f helmfile.yaml.gotmpl -e "$PROFILE" sync --concurrency "$CONCURRENCY" --selector 'layer=app'; then
    echo "[-] Actor deployment failed! Gathering diagnostics..."
    echo ""
    echo "=== AsyncActor CRDs ==="
    kubectl get asyncactor -n "$NAMESPACE" || true
    echo ""
    echo "=== Actor Pod Status ==="
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=actor -o wide || true
    echo ""
    echo "=== Crossplane Provider Logs ==="
    kubectl logs -n crossplane-system -l pkg.crossplane.io/revision --tail=100 --all-containers=true || true
    echo ""
    echo "=== Injector Logs ==="
    kubectl logs -n "$SYSTEM_NAMESPACE" -l app.kubernetes.io/name=asya-injector --tail=100 || true
    echo ""
    echo "=== Failed Actor Pods (if any) ==="
    kubectl describe pods -n "$NAMESPACE" -l app.kubernetes.io/component=actor | grep -A 20 "State.*Waiting\|State.*Terminated" || true
    exit 1
  fi
  echo "[+] Application layer deployed"
}
echo

# Run Helm tests (can be disabled with SKIP_HELM_TESTS=true)
if [ "${SKIP_HELM_TESTS:-false}" = "true" ]; then
  echo "[!] Skipping Helm tests (SKIP_HELM_TESTS=true)"
  echo
else
  echo "[.] Running Helm tests..."
  time {
    cd "$CHARTS_DIR"

    # Add timeout and better error handling
    HELM_TEST_TIMEOUT="${HELM_TEST_TIMEOUT:-300}"
    echo "[.] Helm test timeout: ${HELM_TEST_TIMEOUT}s"

    TEST_OUTPUT=$(helmfile -f helmfile.yaml.gotmpl -e "$PROFILE" test --concurrency "$CONCURRENCY" --timeout "$HELM_TEST_TIMEOUT" --logs 2>&1) || TEST_EXIT_CODE=$?
    echo "$TEST_OUTPUT"

    if [ "${TEST_EXIT_CODE:-0}" -ne 0 ]; then
      case "$TEST_OUTPUT" in
        *"Phase: "*"Failed"*)
          echo "[-] Helm tests failed! Gathering diagnostics..."
          echo ""

          echo "=== Helm Release Status ==="
          helm list -n "$NAMESPACE" || true
          helm list -n "$SYSTEM_NAMESPACE" || true
          echo ""

          echo "=== All Pods (including completed/failed) ==="
          kubectl get pods -n "$NAMESPACE" -o wide || true
          kubectl get pods -n "$SYSTEM_NAMESPACE" -o wide || true
          echo ""

          echo "=== Recent Events (namespace: $NAMESPACE) ==="
          kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' | tail -50 || true
          echo ""

          echo "=== Recent Events (namespace: $SYSTEM_NAMESPACE) ==="
          kubectl get events -n "$SYSTEM_NAMESPACE" --sort-by='.lastTimestamp' | tail -50 || true
          echo ""

          echo "=== Test Pod Logs (if still available) ==="
          for ns in "$NAMESPACE" "$SYSTEM_NAMESPACE"; do
            kubectl get pods -n "$ns" -l 'helm.sh/hook=test' -o name 2> /dev/null | while read -r pod; do
              [ -z "$pod" ] && continue
              echo "--- Logs from $pod (namespace: $ns) ---"
              kubectl logs -n "$ns" "$pod" --tail=100 || true
              echo ""
            done
          done

          exit 1
          ;;
        *"unable to get pod logs"*"pods "*"not found"*)
          echo "[!] Helm test command failed trying to fetch logs from deleted test pods"
          echo "[.] Checking if all tests actually passed..."
          if [[ "$TEST_OUTPUT" == *"Phase: "*"Succeeded"* ]] && ! [[ "$TEST_OUTPUT" == *"Phase: "*"Failed"* ]]; then
            echo "[+] All tests passed (ignoring log fetch errors for deleted pods)"
          else
            echo "[-] Unable to determine test status, failing deployment"
            exit 1
          fi
          ;;
        *)
          echo "[-] Helm tests failed with unexpected error"
          exit 1
          ;;
      esac
    fi
    echo "[+] All Helm tests completed successfully"
    echo
  }
fi

# Phase 8: Wait for Crossplane to reconcile all AsyncActor claims
echo "[.] Phase 8: Waiting for Crossplane to reconcile AsyncActor claims..."
time {
  if ! kubectl wait --for=condition=Ready asyncactor --all \
    -n "$NAMESPACE" --timeout=120s; then
    echo "[!] Warning: Not all AsyncActors reconciled"
    echo "[.] Current AsyncActor status:"
    kubectl get asyncactors -n "$NAMESPACE"
  else
    TOTAL_ACTORS=$(kubectl get asyncactors -n "$NAMESPACE" --no-headers 2> /dev/null | wc -l)
    echo "[+] All $TOTAL_ACTORS AsyncActors reconciled (condition=Ready)"
  fi
}
echo

# Phase 9: Wait for actor pods to scale up and be ready
echo "[.] Phase 9: Waiting for actor pods to be ready..."
time {
  # Give KEDA time to create HPAs and scale up pods
  sleep 5

  if ! kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/component=actor \
    -n "$NAMESPACE" \
    --timeout=120s 2> /dev/null; then
    echo "[!] Warning: Some actor pods may not be ready yet"
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=actor
  else
    READY_PODS=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=actor --field-selector=status.phase=Running --no-headers 2> /dev/null | wc -l)
    echo "[+] All $READY_PODS actor pods are ready"
  fi
}
echo

# Phase 10: Print detailed component status and save logs
echo "[.] Phase 10: Running diagnostics..."
time {
  "$SCRIPT_DIR/debug.sh" diagnostics
}
echo

# Save logs to file for debugging
LOGS_DIR="$SCRIPT_DIR/../.logs"
mkdir -p "$LOGS_DIR"

INJECTOR_LOGS="$LOGS_DIR/injector-$(date +%Y%m%d-%H%M%S).log"
echo "[.] Saving injector logs to: $INJECTOR_LOGS"
kubectl logs -n "$SYSTEM_NAMESPACE" -l app.kubernetes.io/name=asya-injector --tail=1000 > "$INJECTOR_LOGS" 2>&1 || true

CROSSPLANE_LOGS="$LOGS_DIR/crossplane-$(date +%Y%m%d-%H%M%S).log"
echo "[.] Saving Crossplane provider logs to: $CROSSPLANE_LOGS"
kubectl logs -n crossplane-system -l pkg.crossplane.io/revision --tail=1000 --all-containers=true > "$CROSSPLANE_LOGS" 2>&1 || true

echo "[+] Logs saved"
echo

echo "=== Deployment Complete (Crossplane) ==="
echo "Injector logs saved to: $INJECTOR_LOGS"
echo "Crossplane logs saved to: $CROSSPLANE_LOGS"
echo ""
echo "Next steps (from the current directory):"
echo "$ make trigger-tests"
echo "To just port-forward services, run:"
echo "$ make port-forward-up"
echo "$ make port-forward-down"
