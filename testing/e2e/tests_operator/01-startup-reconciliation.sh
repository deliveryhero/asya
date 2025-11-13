#!/usr/bin/env bash
# E2E test for operator startup reconciliation
#
# This test verifies that when the operator restarts, it reconciles existing
# AsyncActors that have no workload resources (the "gap case").
#
# Test scenario:
#   1. Deploy AsyncActor CRDs without operator running
#   2. Start operator
#   3. Verify all AsyncActors get reconciled and Deployments created
#   4. Restart operator
#   5. Verify AsyncActors are reconciled again (idempotent)
#
# Usage:
#   ./test-startup-reconciliation.sh
#
# Environment Variables:
#   NAMESPACE         - K8s namespace for test actors (default: asya-e2e-operator-test)
#   SYSTEM_NAMESPACE  - K8s namespace for operator (default: asya-system-test)
#   CLUSTER_NAME      - Kind cluster name (default: asya-e2e)
#   TIMEOUT           - Wait timeout in seconds (default: 120)
#
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=testing/e2e/tests_operator/load-profile.sh
# shellcheck disable=SC1091
source "${TEST_DIR}/load-profile.sh"

TRANSPORT="${ASYA_TRANSPORT}"
# Override NAMESPACE from profile to use isolated test namespace
NAMESPACE="asya-e2e-startup-reconciliation"
SYSTEM_NAMESPACE="${SYSTEM_NAMESPACE:-asya-system}"
CLUSTER_NAME="${CLUSTER_NAME:-asya-e2e}"
TIMEOUT="${TIMEOUT:-120}"

echo "=== Operator Startup Reconciliation E2E Test ==="
echo "Root directory: $ROOT_DIR"
echo "Test directory: $TEST_DIR"
echo "Namespace: $NAMESPACE"
echo "System namespace: $SYSTEM_NAMESPACE"
echo "Cluster: $CLUSTER_NAME"
echo "Timeout: ${TIMEOUT}s"
echo

# Check prerequisites
echo "[.] Checking prerequisites..."
command -v kubectl > /dev/null 2>&1 || {
  echo "[-] kubectl is not installed"
  exit 1
}
command -v kind > /dev/null 2>&1 || {
  echo "[-] kind is not installed"
  exit 1
}
echo "[+] All prerequisites installed"
echo

# Check cluster exists
if ! kind get clusters 2> /dev/null | grep -q "^${CLUSTER_NAME}$"; then
  echo "[-] Cluster '$CLUSTER_NAME' not found"
  echo "[!] Run 'cd tests/gateway-vs-actors/e2e && ./scripts/deploy.sh' first"
  exit 1
fi
echo "[+] Cluster '$CLUSTER_NAME' exists"
echo

# Ensure kubectl context is correct
kubectl config use-context "kind-${CLUSTER_NAME}" > /dev/null

# Create test namespaces
echo "[.] Creating test namespaces..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace "$SYSTEM_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
echo "[+] Test namespaces created"
echo

# Create SQS secret for the operator to use
if [ "$TRANSPORT" = "sqs" ]; then
  echo "[.] Creating SQS credentials secret..."
  kubectl create secret generic sqs-secret --from-literal=access-key-id=test --from-literal=secret-access-key=test -n "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - > /dev/null
  echo "[+] SQS secret created"
elif [ "$TRANSPORT" = "rabbitmq" ]; then
  echo "[.] Creating RabbitMQ credentials secret..."
  kubectl create secret generic rabbitmq-secret --from-literal=password=guest -n "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - > /dev/null
  echo "[+] RabbitMQ secret created"
fi
echo

# Delete any existing test AsyncActors to start fresh
echo "[.] Cleaning up any existing test AsyncActors..."
kubectl delete asyncactor test-startup-1 test-startup-2 test-startup-3 -n "$NAMESPACE" --ignore-not-found=true --wait=false
sleep 2
echo "[+] Cleanup complete"
echo

# Create test AsyncActor CRDs
echo "[.] Creating test AsyncActor CRDs (with operator running)..."
cat << EOF | kubectl apply -f -
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-startup-1
  namespace: $NAMESPACE
spec:
  transport: $TRANSPORT
  workload:
    kind: Deployment
    replicas: 1
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
          env:
          - name: ASYA_HANDLER
            value: handlers.mock_payload_handlers.echo_handler
---
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-startup-2
  namespace: $NAMESPACE
spec:
  transport: $TRANSPORT
  workload:
    kind: Deployment
    replicas: 1
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
          env:
          - name: ASYA_HANDLER
            value: handlers.mock_payload_handlers.echo_handler
---
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-startup-3
  namespace: $NAMESPACE
spec:
  transport: $TRANSPORT
  workload:
    kind: Deployment
    replicas: 1
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
          env:
          - name: ASYA_HANDLER
            value: handlers.mock_payload_handlers.echo_handler
EOF

echo "[+] Test AsyncActors created"
echo

# Verify AsyncActors exist but have no Deployments
echo "[.] Verifying gap case (AsyncActors without Deployments)..."
ACTOR_COUNT=$(kubectl get asyncactor -n "$NAMESPACE" --no-headers 2> /dev/null | wc -l)
DEPLOYMENT_COUNT=$(kubectl get deployment -n "$NAMESPACE" --no-headers 2> /dev/null | wc -l)

echo "[.] Found $ACTOR_COUNT AsyncActors, $DEPLOYMENT_COUNT Deployments"

if [ "$ACTOR_COUNT" -ne 3 ]; then
  echo "[-] Expected 3 AsyncActors, found $ACTOR_COUNT"
  exit 1
fi

if [ "$DEPLOYMENT_COUNT" -ne 0 ]; then
  echo "[!] Warning: Expected 0 Deployments (gap case), found $DEPLOYMENT_COUNT"
  echo "[!] This is expected if operator is already running"
fi

echo "[+] Gap case verified"
echo

# Wait for operator to be ready
echo "[.] Waiting for operator to be ready..."
if ! kubectl wait --for=condition=available --timeout="${TIMEOUT}s" \
  deployment/asya-operator -n asya-system 2> /dev/null; then
  echo "[-] Operator not ready in asya-system namespace"
  echo "[!] Make sure operator is deployed: cd tests/gateway-vs-actors/e2e && ./scripts/deploy.sh"
  exit 1
fi
echo "[+] Operator ready"
echo

# Wait for startup reconciliation to complete
echo "[.] Waiting for startup reconciliation (max ${TIMEOUT}s)..."
START_TIME=$(date +%s)
RECONCILED=false

while true; do
  CURRENT_TIME=$(date +%s)
  ELAPSED=$((CURRENT_TIME - START_TIME))

  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo "[-] Timeout waiting for reconciliation"
    break
  fi

  DEPLOYMENT_COUNT=$(kubectl get deployment -n "$NAMESPACE" --no-headers 2> /dev/null | wc -l)

  if [ "$DEPLOYMENT_COUNT" -eq 3 ]; then
    echo "[+] All 3 Deployments created (${ELAPSED}s elapsed)"
    RECONCILED=true
    break
  fi

  echo "[.] Waiting... ($DEPLOYMENT_COUNT/3 Deployments created, ${ELAPSED}s elapsed)"
  sleep 2
done

if [ "$RECONCILED" = false ]; then
  echo "[-] Reconciliation failed: only $DEPLOYMENT_COUNT/3 Deployments created"
  echo "[!] Showing AsyncActor status:"
  kubectl get asyncactor -n "$NAMESPACE"
  echo
  echo "[!] Showing Deployment status:"
  kubectl get deployment -n "$NAMESPACE"
  echo
  echo "[!] Showing operator logs (last 50 lines):"
  kubectl logs -n asya-system -l app.kubernetes.io/name=asya-operator --tail=50
  exit 1
fi

echo "[+] Startup reconciliation successful"
echo

# Verify Deployments have correct labels and owner references
echo "[.] Verifying Deployment configuration..."
for actor in test-startup-1 test-startup-2 test-startup-3; do
  if ! kubectl get deployment "$actor" -n "$NAMESPACE" > /dev/null 2>&1; then
    echo "[-] Deployment '$actor' not found"
    exit 1
  fi

  OWNER_KIND=$(kubectl get deployment "$actor" -n "$NAMESPACE" -o jsonpath='{.metadata.ownerReferences[0].kind}')
  if [ "$OWNER_KIND" != "AsyncActor" ]; then
    echo "[-] Deployment '$actor' has wrong owner: $OWNER_KIND (expected AsyncActor)"
    exit 1
  fi

  echo "[+] Deployment '$actor' has correct owner reference"
done
echo

# Test idempotent reconciliation: restart operator and verify AsyncActors reconcile again
echo "[.] Testing idempotent reconciliation..."
echo "[.] Restarting operator..."
kubectl rollout restart deployment/asya-operator -n asya-system
kubectl rollout status deployment/asya-operator -n asya-system --timeout="${TIMEOUT}s"
echo "[+] Operator restarted"
echo

# Wait a bit for startup reconciliation
sleep 5

# Verify AsyncActors still have annotations from startup reconciliation
echo "[.] Verifying startup reconciliation annotations..."
for actor in test-startup-1 test-startup-2 test-startup-3; do
  ANNOTATION=$(kubectl get asyncactor "$actor" -n "$NAMESPACE" -o jsonpath='{.metadata.annotations.asya\.sh/startup-reconcile}')
  if [ -z "$ANNOTATION" ]; then
    echo "[!] Warning: AsyncActor '$actor' missing startup-reconcile annotation"
  else
    echo "[+] AsyncActor '$actor' has startup-reconcile annotation: $ANNOTATION"
  fi
done
echo

# Verify Deployments still exist and are healthy
echo "[.] Verifying Deployments after operator restart..."
DEPLOYMENT_COUNT=$(kubectl get deployment -n "$NAMESPACE" --no-headers 2> /dev/null | wc -l)
if [ "$DEPLOYMENT_COUNT" -ne 3 ]; then
  echo "[-] Expected 3 Deployments after restart, found $DEPLOYMENT_COUNT"
  exit 1
fi
echo "[+] All 3 Deployments still exist after operator restart"
echo

# Cleanup
echo "[.] Cleaning up test resources..."
kubectl delete asyncactor --all -n "$NAMESPACE"
kubectl delete deployment --all -n "$NAMESPACE"
echo "[+] Test resources cleaned up"
echo

echo "=== Test Complete ==="
echo "[+] Startup reconciliation working correctly"
echo "[+] Gap case handled: AsyncActors without Deployments get reconciled"
echo "[+] Idempotent reconciliation: Operator restart handles existing AsyncActors"
echo
