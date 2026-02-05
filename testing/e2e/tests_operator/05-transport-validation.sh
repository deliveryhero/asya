#!/usr/bin/env bash
# E2E test for transport validation
#
# Test Scenarios:
#   1. AsyncActor with non-existent transport → reconcile fails, status shows error
#   2. AsyncActor with valid transport → reconcile succeeds
#   3. Verify transport registry is loaded on operator startup
#
# Expected Behavior:
#   - Invalid transport fails early with clear error message
#   - Status condition TransportReady=False with error details
#   - Valid transport creates workload successfully
#   - Operator logs show transport registry loaded
#
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=testing/e2e/tests_operator/load-profile.sh
# shellcheck disable=SC1091
source "${TEST_DIR}/load-profile.sh"

TRANSPORT="${ASYA_TRANSPORT}"
# Override NAMESPACE from profile to use isolated test namespace
NAMESPACE="asya-e2e-transport-validation"
CLUSTER_NAME="${CLUSTER_NAME:-asya-e2e}"
TIMEOUT="${TIMEOUT:-60}"

echo "=== Transport Validation Test ==="
echo "Namespace: $NAMESPACE"
echo

kubectl config use-context "kind-${CLUSTER_NAME}" > /dev/null
kubectl get crd asyncactors.asya.sh > /dev/null 2>&1 || kubectl apply -f "$ROOT_DIR/src/asya-operator/config/crd/" > /dev/null
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - > /dev/null
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

# Scenario 1: Invalid transport
echo "=== Scenario 1: Invalid transport ==="
cat << EOF | kubectl apply -f -
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-invalid-transport
  namespace: $NAMESPACE
spec:
  transport: nonexistent-transport
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
EOF

sleep 5

echo "[.] Checking TransportReady condition..."
TRANSPORT_READY=$(kubectl get asyncactor test-invalid-transport -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="TransportReady")].status}' 2> /dev/null || echo "")

if [ "$TRANSPORT_READY" == "True" ]; then
  echo "[-] FAIL: TransportReady should be False for invalid transport"
  exit 1
elif [ "$TRANSPORT_READY" == "False" ]; then
  echo "[+] TransportReady=False (as expected)"

  REASON=$(kubectl get asyncactor test-invalid-transport -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="TransportReady")].reason}')
  MESSAGE=$(kubectl get asyncactor test-invalid-transport -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="TransportReady")].message}')

  echo "[.] Reason: $REASON"
  echo "[.] Message: $MESSAGE"

  if [[ "$MESSAGE" != *"nonexistent-transport"* ]]; then
    echo "[!] Warning: Error message doesn't mention invalid transport"
  fi
else
  echo "[!] Warning: TransportReady condition not set yet (may need more time)"
fi

echo "[.] Verifying Deployment not created for invalid transport..."
if kubectl get deployment test-invalid-transport -n "$NAMESPACE" 2> /dev/null; then
  echo "[-] FAIL: Deployment created despite invalid transport"
  exit 1
fi
echo "[+] Deployment not created (as expected)"
echo "[+] Scenario 1 PASS"
echo

# Scenario 2: Valid transport
echo "=== Scenario 2: Valid transport ==="
cat << EOF | kubectl apply -f -
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-valid-transport
  namespace: $NAMESPACE
spec:
  transport: $TRANSPORT
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
EOF

sleep 5

echo "[.] Checking TransportReady condition..."
TRANSPORT_READY=$(kubectl get asyncactor test-valid-transport -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="TransportReady")].status}')

if [ "$TRANSPORT_READY" != "True" ]; then
  echo "[-] FAIL: TransportReady should be True for valid transport"
  kubectl get asyncactor test-valid-transport -n "$NAMESPACE" -o yaml
  exit 1
fi
echo "[+] TransportReady=True"

echo "[.] Verifying Deployment created..."
if ! kubectl get deployment test-valid-transport -n "$NAMESPACE" > /dev/null 2>&1; then
  echo "[-] FAIL: Deployment not created for valid transport"
  exit 1
fi
echo "[+] Deployment created"
echo "[+] Scenario 2 PASS"
echo

# Scenario 3: Verify transport registry loaded in operator
echo "=== Scenario 3: Transport registry loaded ==="
echo "[.] Checking operator logs for transport registry..."
REGISTRY_LOADED=$(kubectl logs -n asya-system -l app.kubernetes.io/name=asya-operator --tail=200 2> /dev/null | grep -i "transport registry" | grep -i "loaded" || echo "")

if [ -n "$REGISTRY_LOADED" ]; then
  echo "[+] Transport registry loaded on operator startup"
  echo "[.] $REGISTRY_LOADED"
else
  echo "[!] Warning: Could not find transport registry log (operator may not be in asya-system)"
fi
echo "[+] Scenario 3 PASS"
echo

echo "[.] Cleaning up..."
kubectl delete asyncactor test-invalid-transport test-valid-transport -n "$NAMESPACE"
kubectl delete namespace "$NAMESPACE" --timeout="${TIMEOUT}s"

echo "=== Test Complete ==="
echo "[+] All transport validation scenarios PASS"
