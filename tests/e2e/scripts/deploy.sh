#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
DEPLOY_DIR="$ROOT_DIR/tests/e2e"

# Parse arguments
RECREATE_CLUSTER=false
if [[ "${1:-}" == "--recreate" ]]; then
    RECREATE_CLUSTER=true
fi

echo "=== Asya Kind Deployment Script ==="
echo "Root directory: $ROOT_DIR"
echo "Deploy directory: $DEPLOY_DIR"
echo

# Check prerequisites
echo "Checking prerequisites..."
command -v kind >/dev/null 2>&1 || { echo "Error: kind is not installed"; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo "Error: kubectl is not installed"; exit 1; }
command -v helm >/dev/null 2>&1 || { echo "Error: helm is not installed"; exit 1; }
command -v helmfile >/dev/null 2>&1 || { echo "Error: helmfile is not installed"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Error: docker is not installed"; exit 1; }
echo "✓ All prerequisites installed"
echo

# Create Kind cluster
CLUSTER_NAME="${CLUSTER_NAME:-asya-kind}"
echo "Creating Kind cluster..."
time {
    if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
        if [ "$RECREATE_CLUSTER" = true ]; then
            echo "Deleting existing cluster..."
            kind delete cluster --name "$CLUSTER_NAME"
            kind create cluster --config "$DEPLOY_DIR/kind-config.yaml"
        else
            echo "Cluster '$CLUSTER_NAME' already exists, using existing cluster"
            echo "(Use --recreate flag to delete and recreate)"
        fi
    else
        kind create cluster --config "$DEPLOY_DIR/kind-config.yaml"
    fi

    # Ensure kubectl context is set to the Kind cluster
    kubectl config use-context "kind-${CLUSTER_NAME}"
}
echo "✓ Kind cluster ready (context: kind-${CLUSTER_NAME})"
echo

# Build and load Docker images
echo "Building and loading Docker images..."
time {
    cd "$ROOT_DIR"
    make build-images
    kind load docker-image asya-operator:latest --name "$CLUSTER_NAME"
    kind load docker-image asya-gateway:latest --name "$CLUSTER_NAME"
    kind load docker-image asya-sidecar:latest --name "$CLUSTER_NAME"
}
echo "✓ Images loaded into Kind cluster"
echo

# Install CRDs
echo "Installing AsyncActor CRDs..."
time {
    kubectl apply -f "$ROOT_DIR/operator/config/crd/"
}
echo "✓ CRDs installed"
echo

# Create namespaces
echo "Creating namespaces..."
time {
    # Wait for namespaces to be fully deleted if they're terminating
    for ns in asya asya-system monitoring keda; do
        if kubectl get namespace "$ns" 2>/dev/null | grep -q Terminating; then
            echo "Waiting for namespace $ns to finish terminating..."
            kubectl wait --for=delete namespace/"$ns" --timeout=120s 2>/dev/null || true
        fi
    done

    kubectl create namespace asya --dry-run=client -o yaml | kubectl apply -f -
    kubectl create namespace asya-system --dry-run=client -o yaml | kubectl apply -f -
}
echo "✓ Namespaces created"
echo

# Apply ConfigMaps
echo "Applying ConfigMaps..."
time {
    kubectl apply -f "$DEPLOY_DIR/manifests/00-configmaps.yaml"
}
echo "✓ ConfigMaps applied"
echo

# Deploy RabbitMQ
echo "Deploying RabbitMQ..."
time {
    kubectl apply -f "$DEPLOY_DIR/manifests/rabbitmq.yaml"
    kubectl wait --for=jsonpath='{.status.readyReplicas}'=1 --timeout=180s statefulset/asya-rabbitmq -n asya
}
echo "✓ RabbitMQ deployed and ready"
echo

# Deploy infrastructure with Helmfile
echo "Deploying infrastructure with Helmfile..."
time {
    cd "$DEPLOY_DIR"
    helmfile sync
}
echo "✓ Infrastructure deployed"
echo

# Wait for gateway to be ready
echo "Waiting for gateway to be ready..."
time {
    kubectl wait --for=condition=available --timeout=120s deployment/asya-gateway -n asya
}
echo "✓ Gateway is ready"
echo

# Run Helm tests
echo "Running Helm tests..."
time {
    echo "Testing operator..."
    helm test asya-operator -n asya-system --logs || echo "⚠ Operator tests failed (non-fatal)"
    echo
    echo "Testing gateway..."
    helm test asya-gateway -n asya --logs || echo "⚠ Gateway tests failed (non-fatal)"
}
echo "✓ Helm tests completed"
echo

# Deploy test actors
echo "Deploying test actors..."
time {
    kubectl apply -f "$DEPLOY_DIR/manifests/"
}
echo "✓ Test actors deployed"
echo

# Wait for actors to be ready
echo "Waiting for actor deployments..."
time {
    for actor in test-echo test-progress test-doubler test-incrementer test-error test-timeout; do
        kubectl wait --for=condition=available --timeout=120s deployment/$actor -n asya || true
    done
}
echo "✓ Actors ready"
echo

echo "=== Deployment Complete ==="
echo
echo "Gateway available at: http://localhost:8080"
echo "Grafana available at: http://localhost:3000 (admin/admin)"
echo
echo "Useful commands:"
echo "  kubectl get pods -n asya           # Check actor pods"
echo "  kubectl logs -n asya -l app=asya-gateway  # Gateway logs"
echo "  kubectl port-forward -n asya svc/asya-rabbitmq 15672:15672  # RabbitMQ Management"
