#!/usr/bin/env bash
# E2E test for concurrent AsyncActor operations
#
# Test Scenarios:
#   1. Create 10 AsyncActors simultaneously → all reconcile successfully
#   2. Update 10 AsyncActors simultaneously → no conflicts
#   3. Delete 10 AsyncActors simultaneously → all deleted cleanly
#   4. Rapid create/delete cycles → no leaked resources
#
# Expected Behavior:
#   - All concurrent creates succeed
#   - No race conditions or conflicts
#   - All Deployments created within timeout
#   - Cleanup completes without errors
#
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=testing/e2e/tests_operator/load-profile.sh
# shellcheck disable=SC1091
source "${TEST_DIR}/load-profile.sh"

TRANSPORT="${ASYA_TRANSPORT}"
# Override NAMESPACE from profile to use isolated test namespace
NAMESPACE="asya-e2e-concurrent-operations"
CLUSTER_NAME="${CLUSTER_NAME:-asya-e2e}"
TIMEOUT="${TIMEOUT:-120}"
ACTOR_COUNT=10

echo "=== Concurrent AsyncActor Operations Test ==="
echo "Namespace: $NAMESPACE"
echo "Actor count: $ACTOR_COUNT"
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

# Scenario 1: Concurrent creation
echo "=== Scenario 1: Concurrent creation of $ACTOR_COUNT AsyncActors ==="
START_TIME=$(date +%s)

echo "[.] Creating $ACTOR_COUNT AsyncActors in parallel..."
for i in $(seq 1 $ACTOR_COUNT); do
  cat << EOF | kubectl apply -f - &
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-concurrent-$i
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
EOF
done

wait
CREATE_TIME=$(($(date +%s) - START_TIME))
echo "[+] All AsyncActors created in ${CREATE_TIME}s"

echo "[.] Waiting for all Deployments (max ${TIMEOUT}s)..."
START_WAIT=$(date +%s)
RECONCILED=0

while true; do
  ELAPSED=$(($(date +%s) - START_WAIT))
  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo "[-] Timeout waiting for Deployments"
    break
  fi

  DEPLOYMENT_COUNT=$(kubectl get deployment -n "$NAMESPACE" --no-headers 2> /dev/null | wc -l)
  if [ "$DEPLOYMENT_COUNT" -eq "$ACTOR_COUNT" ]; then
    RECONCILED=$ACTOR_COUNT
    echo "[+] All $ACTOR_COUNT Deployments created (${ELAPSED}s elapsed)"
    break
  fi

  echo "[.] Waiting... ($DEPLOYMENT_COUNT/$ACTOR_COUNT Deployments, ${ELAPSED}s elapsed)"
  sleep 2
done

if [ "$RECONCILED" -ne "$ACTOR_COUNT" ]; then
  echo "[-] FAIL: Only $DEPLOYMENT_COUNT/$ACTOR_COUNT Deployments created"
  kubectl get asyncactor -n "$NAMESPACE"
  exit 1
fi
echo "[+] Scenario 1 PASS: All concurrent creates succeeded"
echo

# Scenario 2: Concurrent updates
echo "=== Scenario 2: Concurrent updates ==="
echo "[.] Updating replicas on all $ACTOR_COUNT AsyncActors..."
START_TIME=$(date +%s)

for i in $(seq 1 $ACTOR_COUNT); do
  kubectl patch asyncactor "test-concurrent-$i" -n "$NAMESPACE" --type=merge -p '{"spec":{"workload":{"replicas":2}}}' &
done

wait
UPDATE_TIME=$(($(date +%s) - START_TIME))
echo "[+] All updates applied in ${UPDATE_TIME}s"

sleep 5

echo "[.] Verifying all Deployments updated to replicas=2..."
for i in $(seq 1 $ACTOR_COUNT); do
  REPLICAS=$(kubectl get deployment "test-concurrent-$i" -n "$NAMESPACE" -o jsonpath='{.spec.replicas}' 2> /dev/null || echo "0")
  if [ "$REPLICAS" != "2" ]; then
    echo "[-] FAIL: test-concurrent-$i has $REPLICAS replicas (expected 2)"
    exit 1
  fi
done
echo "[+] All Deployments updated"
echo "[+] Scenario 2 PASS: Concurrent updates succeeded"
echo

# Scenario 3: Concurrent deletion
echo "=== Scenario 3: Concurrent deletion ==="
echo "[.] Deleting all $ACTOR_COUNT AsyncActors..."
START_TIME=$(date +%s)

for i in $(seq 1 $ACTOR_COUNT); do
  kubectl delete asyncactor "test-concurrent-$i" -n "$NAMESPACE" &
done

wait
DELETE_TIME=$(($(date +%s) - START_TIME))
echo "[+] All deletions initiated in ${DELETE_TIME}s"

echo "[.] Waiting for all resources to be deleted..."
sleep 5

REMAINING_ACTORS=$(kubectl get asyncactor -n "$NAMESPACE" --no-headers 2> /dev/null | wc -l)
REMAINING_DEPLOYMENTS=$(kubectl get deployment -n "$NAMESPACE" --no-headers 2> /dev/null | wc -l)

if [ "$REMAINING_ACTORS" -ne 0 ] || [ "$REMAINING_DEPLOYMENTS" -ne 0 ]; then
  echo "[-] FAIL: Resources not fully deleted (actors=$REMAINING_ACTORS, deployments=$REMAINING_DEPLOYMENTS)"
  exit 1
fi
echo "[+] All resources deleted"
echo "[+] Scenario 3 PASS: Concurrent deletion succeeded"
echo

# Scenario 4: Rapid create/delete cycle
echo "=== Scenario 4: Rapid create/delete cycles ==="
echo "[.] Creating and deleting AsyncActor 5 times rapidly..."

for cycle in $(seq 1 5); do
  echo "[.] Cycle $cycle..."

  cat << EOF | kubectl apply -f - > /dev/null
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-rapid
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

  sleep 1
  kubectl delete asyncactor test-rapid -n "$NAMESPACE" 2> /dev/null || true
  sleep 1
done

echo "[.] Waiting for final cleanup..."
sleep 10

echo "[.] Verifying no leaked resources..."
if kubectl get asyncactor test-rapid -n "$NAMESPACE" 2> /dev/null; then
  echo "[-] FAIL: AsyncActor test-rapid still exists"
  exit 1
fi

if kubectl get deployment test-rapid -n "$NAMESPACE" 2> /dev/null; then
  echo "[-] FAIL: Deployment test-rapid still exists"
  exit 1
fi

echo "[+] No leaked resources"
echo "[+] Scenario 4 PASS: Rapid cycles handled correctly"
echo

echo "[.] Cleaning up..."
kubectl delete namespace "$NAMESPACE" --timeout="${TIMEOUT}s"

echo "=== Test Complete ==="
echo "[+] All concurrent operation scenarios PASS"
echo "[.] Summary:"
echo "    - Created $ACTOR_COUNT AsyncActors concurrently in ${CREATE_TIME}s"
echo "    - Updated $ACTOR_COUNT AsyncActors concurrently in ${UPDATE_TIME}s"
echo "    - Deleted $ACTOR_COUNT AsyncActors concurrently in ${DELETE_TIME}s"
echo "    - Rapid create/delete cycles: no leaks"
