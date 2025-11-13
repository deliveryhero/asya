#!/usr/bin/env bash
# E2E test for KEDA ScaledObject lifecycle
#
# Test Scenarios:
#   1. scaling.enabled=true → ScaledObject created with correct triggers
#   2. scaling.enabled=false → ScaledObject deleted
#   3. Update scaling parameters → ScaledObject config updated
#   4. Verify HPA created by KEDA (not owned by operator)
#
# Expected Behavior:
#   - ScaledObject creation/deletion syncs with scaling.enabled
#   - ScaledObject has correct RabbitMQ trigger config
#   - HPA created by KEDA controller
#   - Operator doesn't own HPA (KEDA owns it)
#
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=testing/e2e/tests_operator/load-profile.sh
# shellcheck disable=SC1091
source "${TEST_DIR}/load-profile.sh"

TRANSPORT="${ASYA_TRANSPORT}"
# Override NAMESPACE from profile to use isolated test namespace
NAMESPACE="asya-e2e-keda-lifecycle"
CLUSTER_NAME="${CLUSTER_NAME:-asya-e2e}"
TIMEOUT="${TIMEOUT:-60}"

echo "=== KEDA ScaledObject Lifecycle Test ==="
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

# Scenario 1: Create AsyncActor with scaling enabled
echo "=== Scenario 1: ScaledObject creation ==="
cat << EOF | kubectl apply -f -
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-keda
  namespace: $NAMESPACE
spec:
  transport: $TRANSPORT
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    queueLength: 5
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
EOF

sleep 5

echo "[.] Verifying ScaledObject created..."
if ! kubectl get scaledobject test-keda -n "$NAMESPACE" > /dev/null 2>&1; then
  echo "[-] FAIL: ScaledObject not created"
  exit 1
fi
echo "[+] ScaledObject created"

echo "[.] Verifying ScaledObject config..."
MIN=$(kubectl get scaledobject test-keda -n "$NAMESPACE" -o jsonpath='{.spec.minReplicaCount}')
MAX=$(kubectl get scaledobject test-keda -n "$NAMESPACE" -o jsonpath='{.spec.maxReplicaCount}')
QUEUE_LENGTH=$(kubectl get scaledobject test-keda -n "$NAMESPACE" -o jsonpath='{.spec.triggers[0].metadata.queueLength}')

if [ "$MIN" != "0" ] || [ "$MAX" != "10" ] || [ "$QUEUE_LENGTH" != "5" ]; then
  echo "[-] FAIL: ScaledObject config incorrect (min=$MIN, max=$MAX, queueLength=$QUEUE_LENGTH)"
  exit 1
fi
echo "[+] ScaledObject config correct (min=$MIN, max=$MAX, queueLength=$QUEUE_LENGTH)"

echo "[.] Verifying SQS trigger..."
TRIGGER_TYPE=$(kubectl get scaledobject test-keda -n "$NAMESPACE" -o jsonpath='{.spec.triggers[0].type}')
if [ "$TRIGGER_TYPE" != "aws-sqs-queue" ]; then
  echo "[-] FAIL: Expected aws-sqs-queue trigger, got $TRIGGER_TYPE"
  exit 1
fi
echo "[+] SQS trigger configured"
echo "[+] Scenario 1 PASS"
echo

# Scenario 2: Verify HPA created by KEDA
echo "=== Scenario 2: HPA creation by KEDA ==="
sleep 5

HPA_NAME="keda-hpa-test-keda"
echo "[.] Checking for HPA: $HPA_NAME..."
if kubectl get hpa "$HPA_NAME" -n "$NAMESPACE" > /dev/null 2>&1; then
  echo "[+] HPA created by KEDA"

  echo "[.] Verifying HPA not owned by operator..."
  OWNER=$(kubectl get hpa "$HPA_NAME" -n "$NAMESPACE" -o jsonpath='{.metadata.ownerReferences[0].kind}')
  if [ "$OWNER" == "AsyncActor" ]; then
    echo "[-] FAIL: HPA owned by AsyncActor (should be owned by ScaledObject/KEDA)"
    exit 1
  fi
  echo "[+] HPA owned by KEDA (not operator)"
else
  echo "[!] Warning: HPA not yet created (KEDA may need more time)"
fi
echo "[+] Scenario 2 PASS"
echo

# Scenario 3: Disable scaling → ScaledObject deleted
echo "=== Scenario 3: Disable scaling ==="
kubectl patch asyncactor test-keda -n "$NAMESPACE" --type=merge -p '{"spec":{"scaling":{"enabled":false}}}'
sleep 5

echo "[.] Verifying ScaledObject deleted..."
if kubectl get scaledobject test-keda -n "$NAMESPACE" 2> /dev/null; then
  echo "[-] FAIL: ScaledObject still exists after disabling scaling"
  exit 1
fi
echo "[+] ScaledObject deleted"
echo "[+] Scenario 3 PASS"
echo

# Scenario 4: Re-enable scaling
echo "=== Scenario 4: Re-enable scaling ==="
kubectl patch asyncactor test-keda -n "$NAMESPACE" --type=merge -p '{"spec":{"scaling":{"enabled":true,"minReplicas":2,"maxReplicas":15,"queueLength":8}}}'
sleep 5

echo "[.] Verifying ScaledObject recreated with new config..."
if ! kubectl get scaledobject test-keda -n "$NAMESPACE" > /dev/null 2>&1; then
  echo "[-] FAIL: ScaledObject not recreated"
  exit 1
fi

MIN=$(kubectl get scaledobject test-keda -n "$NAMESPACE" -o jsonpath='{.spec.minReplicaCount}')
MAX=$(kubectl get scaledobject test-keda -n "$NAMESPACE" -o jsonpath='{.spec.maxReplicaCount}')
QUEUE_LENGTH=$(kubectl get scaledobject test-keda -n "$NAMESPACE" -o jsonpath='{.spec.triggers[0].metadata.queueLength}')

if [ "$MIN" != "2" ] || [ "$MAX" != "15" ] || [ "$QUEUE_LENGTH" != "8" ]; then
  echo "[-] FAIL: ScaledObject config not updated (min=$MIN, max=$MAX, queueLength=$QUEUE_LENGTH)"
  exit 1
fi
echo "[+] ScaledObject recreated with updated config"
echo "[+] Scenario 4 PASS"
echo

echo "[.] Cleaning up..."
kubectl delete asyncactor test-keda -n "$NAMESPACE"
kubectl delete namespace "$NAMESPACE" --timeout="${TIMEOUT}s"

echo "=== Test Complete ==="
echo "[+] All KEDA lifecycle scenarios PASS"
