#!/usr/bin/env bash
# E2E test for AsyncActor deletion and finalizer cleanup
#
# Test Scenarios:
#   1. Delete AsyncActor → verify all owned resources deleted (Deployment, ScaledObject)
#   2. Verify finalizer removed after cleanup
#   3. Delete AsyncActor during active reconciliation → verify graceful cleanup
#   4. Delete AsyncActor when Deployment already manually deleted → verify no errors
#
# Expected Behavior:
#   - Finalizer prevents deletion until cleanup complete
#   - Owned Deployments deleted via cascade (ownerReferences)
#   - ScaledObjects deleted if scaling enabled
#   - No resources leaked
#   - No namespace stuck in Terminating state
#
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=testing/e2e/tests_operator/load-profile.sh
# shellcheck disable=SC1091
source "${TEST_DIR}/load-profile.sh"

TRANSPORT="${ASYA_TRANSPORT}"
# Override NAMESPACE from profile to use isolated test namespace
NAMESPACE="asya-e2e-deletion-finalizer"
CLUSTER_NAME="${CLUSTER_NAME:-asya-e2e}"
TIMEOUT="${TIMEOUT:-60}"

echo "=== AsyncActor Deletion and Finalizer Test ==="
echo "Namespace: $NAMESPACE"
echo "Cluster: $CLUSTER_NAME"
echo "Transport: $TRANSPORT"
echo

kubectl config use-context "kind-${CLUSTER_NAME}" > /dev/null

echo "[.] Installing CRDs if needed..."
kubectl get crd asyncactors.asya.sh > /dev/null 2>&1 || kubectl apply -f "$ROOT_DIR/src/asya-operator/config/crd/" > /dev/null
echo

echo "[.] Creating test namespace..."
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

# Scenario 1: Normal deletion
echo "=== Scenario 1: Normal AsyncActor deletion ==="
cat << EOF | kubectl apply -f -
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-delete-normal
  namespace: $NAMESPACE
spec:
  transport: $TRANSPORT
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 5
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
EOF

echo "[.] Waiting for Deployment creation..."
kubectl wait --for=condition=available --timeout="${TIMEOUT}"s deployment/test-delete-normal -n "$NAMESPACE" 2> /dev/null || true
sleep 5

echo "[.] Verifying Deployment and ScaledObject exist..."
kubectl get deployment test-delete-normal -n "$NAMESPACE" > /dev/null
kubectl get scaledobject test-delete-normal -n "$NAMESPACE" > /dev/null
echo "[+] Resources created"

echo "[.] Deleting AsyncActor..."
kubectl delete asyncactor test-delete-normal -n "$NAMESPACE" --timeout="${TIMEOUT}"s

echo "[.] Verifying Deployment deleted (cascade)..."
if kubectl get deployment test-delete-normal -n "$NAMESPACE" 2> /dev/null; then
  echo "[-] FAIL: Deployment not deleted"
  exit 1
fi

echo "[.] Verifying ScaledObject deleted..."
if kubectl get scaledobject test-delete-normal -n "$NAMESPACE" 2> /dev/null; then
  echo "[-] FAIL: ScaledObject not deleted"
  exit 1
fi

echo "[+] Scenario 1 PASS: All resources cleaned up"
echo

# Scenario 2: Delete AsyncActor with manually deleted Deployment
echo "=== Scenario 2: Delete AsyncActor after manual Deployment deletion ==="
cat << EOF | kubectl apply -f -
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-delete-orphan
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

sleep 3

echo "[.] Manually deleting Deployment..."
kubectl delete deployment test-delete-orphan -n "$NAMESPACE" --ignore-not-found=true

echo "[.] Deleting AsyncActor (should succeed without errors)..."
kubectl delete asyncactor test-delete-orphan -n "$NAMESPACE" --timeout="${TIMEOUT}"s

echo "[+] Scenario 2 PASS: Deletion succeeded despite missing Deployment"
echo

# Scenario 3: Verify finalizer behavior
echo "=== Scenario 3: Finalizer prevents premature deletion ==="
cat << EOF | kubectl apply -f -
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-finalizer
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

sleep 3

echo "[.] Checking finalizer present..."
FINALIZER=$(kubectl get asyncactor test-finalizer -n "$NAMESPACE" -o jsonpath='{.metadata.finalizers[0]}')
if [ "$FINALIZER" != "asya.sh/finalizer" ]; then
  echo "[-] FAIL: Finalizer not present or incorrect: $FINALIZER"
  exit 1
fi
echo "[+] Finalizer present: $FINALIZER"

echo "[.] Deleting AsyncActor..."
kubectl delete asyncactor test-finalizer -n "$NAMESPACE" --timeout="${TIMEOUT}"s

echo "[.] Verifying AsyncActor fully deleted..."
if kubectl get asyncactor test-finalizer -n "$NAMESPACE" 2> /dev/null; then
  echo "[-] FAIL: AsyncActor still exists"
  exit 1
fi
echo "[+] Scenario 3 PASS: Finalizer removed after cleanup"
echo

echo "[.] Cleaning up test namespace..."
kubectl delete namespace "$NAMESPACE" --timeout="${TIMEOUT}"s

echo "=== Test Complete ==="
echo "[+] All deletion and finalizer scenarios PASS"
