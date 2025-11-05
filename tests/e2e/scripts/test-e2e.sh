#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CLUSTER_NAME="asya-kind"

echo "=== Running E2E Tests against Kind cluster ==="
echo

# Check if cluster exists
if ! kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
    echo "Error: Kind cluster '$CLUSTER_NAME' not found. Run ./scripts/deploy.sh first"
    exit 1
fi

# Ensure kubectl context is set to the Kind cluster
kubectl config use-context "kind-${CLUSTER_NAME}"
echo "✓ Using context: kind-${CLUSTER_NAME}"
echo

# Check if gateway is accessible
echo "Checking gateway health..."
for i in {1..30}; do
    if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
        echo "✓ Gateway is healthy"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "Error: Gateway is not responding"
        exit 1
    fi
    sleep 1
done
echo

# Run E2E tests
echo "Running E2E tests..."
cd "$ROOT_DIR"
export ASYA_GATEWAY_URL=http://localhost:8080
export RABBITMQ_MGMT_URL=http://localhost:15672

# Port-forward RabbitMQ management for tests
kubectl port-forward -n asya svc/asya-rabbitmq 15672:15672 >/dev/null 2>&1 &
PF_PID=$!
trap 'kill $PF_PID 2>/dev/null || true' EXIT

# Wait for port-forward to be ready
sleep 2

# Run pytest
uv run pytest -v tests/e2e/

echo
echo "=== E2E Tests Complete ==="
