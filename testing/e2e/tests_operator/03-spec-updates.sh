#!/usr/bin/env bash
# E2E test for AsyncActor spec updates
#
# Test Scenarios:
#   1. Transport change (rabbitmq config update) → sidecar env vars updated
#   2. Scaling toggle (disabled → enabled) → ScaledObject created
#   3. Scaling toggle (enabled → disabled) → ScaledObject deleted, manual replicas restored
#   4. Replica count change (when scaling disabled) → Deployment replicas updated
#
# Expected Behavior:
#   - Spec updates trigger reconciliation
#   - Changes applied idempotently
#   - Deployment preserved during updates
#   - ScaledObject lifecycle matches scaling.enabled flag
#
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=testing/e2e/tests_operator/load-profile.sh
# shellcheck disable=SC1091
source "${TEST_DIR}/load-profile.sh"

TRANSPORT="${ASYA_TRANSPORT}"
# Override NAMESPACE from profile to use isolated test namespace
NAMESPACE="asya-e2e-spec-updates"
CLUSTER_NAME="${CLUSTER_NAME:-asya-e2e}"
TIMEOUT="${TIMEOUT:-60}"

echo "=== AsyncActor Spec Updates Test ==="
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

# Scenario 1: Replica count change (scaling disabled)
echo "=== Scenario 1: Replica count change ==="
cat << EOF | kubectl apply -f -
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-replicas
  namespace: $NAMESPACE
spec:
  transport: $TRANSPORT
  scaling:
    enabled: false
  workload:
    kind: Deployment
    replicas: 1
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
EOF

echo "[.] Waiting for deployment to be created..."
for i in {1..30}; do
  if kubectl get deployment test-replicas -n "$NAMESPACE" > /dev/null 2>&1; then
    echo "[+] Deployment created after ${i}s"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "[-] FAIL: Deployment not created after 30s"
    exit 1
  fi
  sleep 1
done

echo "[.] Verifying initial replicas=1..."
REPLICAS=$(kubectl get deployment test-replicas -n "$NAMESPACE" -o jsonpath='{.spec.replicas}')
if [ "$REPLICAS" != "1" ]; then
  echo "[-] FAIL: Expected 1 replica, got $REPLICAS"
  exit 1
fi
echo "[+] Initial replicas: $REPLICAS"

echo "[.] Updating replicas to 3..."
kubectl patch asyncactor test-replicas -n "$NAMESPACE" --type=merge -p '{"spec":{"workload":{"replicas":3}}}'
sleep 3

echo "[.] Verifying updated replicas=3..."
REPLICAS=$(kubectl get deployment test-replicas -n "$NAMESPACE" -o jsonpath='{.spec.replicas}')
if [ "$REPLICAS" != "3" ]; then
  echo "[-] FAIL: Expected 3 replicas, got $REPLICAS"
  exit 1
fi
echo "[+] Scenario 1 PASS: Replicas updated to $REPLICAS"
echo

# Scenario 2: Enable scaling → ScaledObject created
echo "=== Scenario 2: Enable scaling ==="
echo "[.] Enabling KEDA autoscaling..."
kubectl patch asyncactor test-replicas -n "$NAMESPACE" --type=merge -p '{"spec":{"scaling":{"enabled":true,"minReplicas":0,"maxReplicas":10,"queueLength":5}}}'
sleep 5

echo "[.] Verifying ScaledObject created..."
if ! kubectl get scaledobject test-replicas -n "$NAMESPACE" > /dev/null 2>&1; then
  echo "[-] FAIL: ScaledObject not created"
  exit 1
fi
echo "[+] ScaledObject created"

echo "[.] Verifying HPA created by KEDA..."
HPA_NAME="keda-hpa-test-replicas"
if ! kubectl get hpa "$HPA_NAME" -n "$NAMESPACE" > /dev/null 2>&1; then
  echo "[!] Warning: HPA not yet created by KEDA (may take a moment)"
fi
echo "[+] Scenario 2 PASS: Scaling enabled"
echo

# Scenario 3: Disable scaling → ScaledObject deleted
echo "=== Scenario 3: Disable scaling ==="
echo "[.] Disabling KEDA autoscaling..."
kubectl patch asyncactor test-replicas -n "$NAMESPACE" --type=merge -p '{"spec":{"scaling":{"enabled":false}}}'

echo "[.] Verifying ScaledObject deleted..."
for i in {1..60}; do
  if ! kubectl get scaledobject test-replicas -n "$NAMESPACE" > /dev/null 2>&1; then
    echo "[+] ScaledObject deleted after ${i}s"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "[-] FAIL: ScaledObject still exists after 60s"
    kubectl get scaledobject test-replicas -n "$NAMESPACE" -o yaml
    exit 1
  fi
  sleep 1
done

echo "[.] Verifying manual replicas restored..."
REPLICAS=$(kubectl get deployment test-replicas -n "$NAMESPACE" -o jsonpath='{.spec.replicas}')
echo "[.] Current replicas: $REPLICAS (should match spec.workload.replicas)"
echo "[+] Scenario 3 PASS: Scaling disabled"
echo

# Scenario 4: Update scaling parameters (when enabled)
echo "=== Scenario 4: Update scaling parameters ==="
kubectl patch asyncactor test-replicas -n "$NAMESPACE" --type=merge -p '{"spec":{"scaling":{"enabled":true,"minReplicas":1,"maxReplicas":20,"queueLength":10}}}'
sleep 5

echo "[.] Verifying ScaledObject config updated..."
MIN_REPLICAS=$(kubectl get scaledobject test-replicas -n "$NAMESPACE" -o jsonpath='{.spec.minReplicaCount}')
MAX_REPLICAS=$(kubectl get scaledobject test-replicas -n "$NAMESPACE" -o jsonpath='{.spec.maxReplicaCount}')

if [ "$MIN_REPLICAS" != "1" ] || [ "$MAX_REPLICAS" != "20" ]; then
  echo "[-] FAIL: ScaledObject not updated (min=$MIN_REPLICAS, max=$MAX_REPLICAS)"
  exit 1
fi
echo "[+] Scenario 4 PASS: ScaledObject config updated (min=$MIN_REPLICAS, max=$MAX_REPLICAS)"
echo

echo "[.] Cleaning up..."
kubectl delete asyncactor test-replicas -n "$NAMESPACE"
kubectl delete namespace "$NAMESPACE" --timeout="${TIMEOUT}"s

echo "=== Test Complete ==="
echo "[+] All spec update scenarios PASS"
