#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHARTS_DIR="$SCRIPT_DIR/../charts"

# Detect CPU cores for parallel operations
NCPU=$(nproc)
CONCURRENCY="${CONCURRENCY:-$NCPU}"

# Parse arguments
RECREATE_CLUSTER=false
if [[ "${1:-}" == "--recreate" ]]; then
  RECREATE_CLUSTER=true
fi

# Validate profile
case "$PROFILE" in
  rabbitmq-minio | sqs-s3) ;;
  *)
    echo "[!] Unknown profile: $PROFILE"
    echo "    Valid profiles: rabbitmq-minio, sqs-s3"
    exit 1
    ;;
esac

CLUSTER_NAME="${CLUSTER_NAME:-asya-e2e-${PROFILE}}"
SYSTEM_NAMESPACE="asya-system"
NAMESPACE="asya-e2e"

export HELMFILE_LOG_LEVEL="${HELMFILE_LOG_LEVEL:-error}"

echo "=== Asya Kind E2e Deployment Script ==="
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

# Create Kind cluster and regenerate manifests in parallel
echo "[.] Setting up cluster and building components..."
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

  # Start manifest generation in parallel
  echo "[.] Regenerating operator manifests..."
  make -C "$ROOT_DIR/src/asya-operator" manifests &
  MANIFEST_PID=$!

  # Start image building in parallel
  echo "[.] Building Docker images..."
  "$ROOT_DIR/src/build-images.sh" &
  BUILD_PID=$!

  # Wait for image builds first (usually faster than cluster)
  if ! wait "$BUILD_PID"; then
    echo "[-] Docker image build failed"
    exit 1
  fi
  echo "[+] Docker images built"

  # Wait for cluster creation
  if [ -n "$CLUSTER_PID" ]; then
    if ! wait "$CLUSTER_PID"; then
      echo "[-] Kind cluster creation failed"
      exit 1
    fi
    kubectl config use-context "kind-${CLUSTER_NAME}"
    echo "[+] Kind cluster ready (context: kind-${CLUSTER_NAME})"
  fi

  # Load Docker images into Kind cluster
  echo "[.] Loading images into Kind cluster..."
  IMAGES_TO_LOAD=(
    "asya-operator:latest"
    "asya-gateway:latest"
    "asya-sidecar:latest"
    "asya-crew:latest"
    "asya-testing:latest"
  )

  LOAD_PIDS=()
  for img in "${IMAGES_TO_LOAD[@]}"; do
    kind load docker-image "$img" --name "$CLUSTER_NAME" &
    LOAD_PIDS+=($!)
  done

  # Wait for manifest generation (runs in parallel with image loading)
  if ! wait "$MANIFEST_PID"; then
    echo "[-] Operator manifest generation failed"
    exit 1
  fi
  echo "[+] Operator manifests regenerated"

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
  echo
}

# Deploy infrastructure layer with Helmfile
# (KEDA, Postgres, Operator, Gateway, Transports, Storages)
echo "[.] Deploying infrastructure layer..."
time {
  cd "$CHARTS_DIR"
  if ! helmfile -f helmfile.yaml.gotmpl -e "$PROFILE" sync --concurrency "$CONCURRENCY" --selector 'layer=infra'; then
    echo "[-] Infrastructure deployment failed! Gathering diagnostics..."
    echo ""
    echo "=== Pod Status ==="
    kubectl get pods -n "$NAMESPACE" -o wide || true
    kubectl get pods -n "$SYSTEM_NAMESPACE" -o wide || true
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
    echo "=== Gateway Previous Logs (if crashed) ==="
    kubectl logs -n "$NAMESPACE" -l app.kubernetes.io/name=asya-gateway --tail=100 --all-containers=true --previous || true
    echo ""
    echo "=== Operator Logs ==="
    kubectl logs -n "$SYSTEM_NAMESPACE" -l app.kubernetes.io/name=asya-operator --tail=50 || true
    echo ""
    echo "=== Migration Job Logs ==="
    kubectl logs -n "$NAMESPACE" -l app.kubernetes.io/component=migration --tail=50 || true
    exit 1
  fi
  echo "[+] Infrastructure layer deployed"
  echo
}

# Deploy application layer with Helmfile (test actors + system actors)
echo "[.] Deploying application layer (actors)..."
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
    echo "=== Operator Logs ==="
    kubectl logs -n "$SYSTEM_NAMESPACE" -l app.kubernetes.io/name=asya-operator --tail=100 || true
    echo ""
    echo "=== Failed Actor Pods (if any) ==="
    kubectl describe pods -n "$NAMESPACE" -l app.kubernetes.io/component=actor | grep -A 20 "State.*Waiting\|State.*Terminated" || true
    exit 1
  fi
  echo "[+] Application layer deployed"
  echo
}

# Run Helm tests
echo "[.] Running Helm tests..."
time {
  cd "$CHARTS_DIR"
  if ! helmfile -f helmfile.yaml.gotmpl -e "$PROFILE" test --concurrency "$CONCURRENCY"; then
    echo "[-] Helm tests failed"
    exit 1
  fi
  echo "[+] All Helm tests completed successfully"
  echo
}

# Wait for actors to be ready
echo "[.] Waiting for actor pods to be ready..."
time {
  if ! kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/component=actor \
    -n "$NAMESPACE" \
    --timeout=120s 2> /dev/null; then
    echo "[!] Warning: Some actor pods may not be ready yet"
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=actor
  else
    echo "[+] All actor pods are ready"
  fi
}
echo

# Print detailed component status
echo "[.] Running diagnostics..."
time {
  "$SCRIPT_DIR/debug.sh" diagnostics
}
echo

echo "=== Deployment Complete ==="
echo "Next steps:"
echo "$ make port-forward-up"
echo "$ make trigger-tests"
echo "$ make port-forward-down"
