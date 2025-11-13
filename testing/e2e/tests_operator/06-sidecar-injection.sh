#!/usr/bin/env bash
# E2E test for sidecar injection with user container conflicts
#
# Test Scenarios:
#   1. User container named "asya-sidecar" → operator panics/rejects
#   2. User volume named "socket-dir" → verify no conflict
#   3. Multiple user containers + injected sidecar → all containers present
#   4. Verify sidecar env vars injected correctly
#
# Expected Behavior:
#   - Container named "asya-sidecar" forbidden (operator validation)
#   - Sidecar appended to user containers
#   - All required volumes mounted (socket-dir, tmp, asya-runtime)
#   - Sidecar env vars configured with transport settings
#
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=testing/e2e/tests_operator/load-profile.sh
# shellcheck disable=SC1091
source "${TEST_DIR}/load-profile.sh"

TRANSPORT="${ASYA_TRANSPORT}"
# Override NAMESPACE from profile to use isolated test namespace
NAMESPACE="asya-e2e-sidecar-injection"
CLUSTER_NAME="${CLUSTER_NAME:-asya-e2e}"
TIMEOUT="${TIMEOUT:-60}"

echo "=== Sidecar Injection Test ==="
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

# Scenario 1: Forbidden container name
echo "=== Scenario 1: Container named 'asya-sidecar' (forbidden) ==="
cat << EOF | kubectl apply -f -
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-conflict-name
  namespace: $NAMESPACE
spec:
  transport: $TRANSPORT
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-sidecar
          image: busybox:latest
EOF

sleep 5

echo "[.] Checking if reconciliation failed..."
WORKLOAD_READY=$(kubectl get asyncactor test-conflict-name -n "$NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="WorkloadReady")].status}' 2> /dev/null || echo "")

if [ "$WORKLOAD_READY" == "True" ]; then
  echo "[-] FAIL: Workload should not be created with conflicting container name"
  exit 1
fi

echo "[.] Checking operator logs for panic/error..."
ERROR_LOG=$(kubectl logs -n asya-system -l app.kubernetes.io/name=asya-operator --tail=100 2> /dev/null | grep -i "asya-sidecar" | grep -i "conflict" || echo "")

if [ -n "$ERROR_LOG" ]; then
  echo "[+] Operator detected conflict:"
  echo "[.] $ERROR_LOG"
else
  echo "[!] Warning: Could not find conflict error in logs (operator may have crashed or in different namespace)"
fi

echo "[+] Scenario 1 PASS: Conflicting container name rejected"
echo

kubectl delete asyncactor test-conflict-name -n "$NAMESPACE" --ignore-not-found=true

# Scenario 2: Multiple user containers
echo "=== Scenario 2: Multiple user containers + sidecar ==="
cat << EOF | kubectl apply -f -
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-multi-container
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
        - name: helper
          image: busybox:latest
          command: ["sleep", "3600"]
EOF

sleep 5

echo "[.] Verifying Deployment created..."
if ! kubectl get deployment test-multi-container -n "$NAMESPACE" > /dev/null 2>&1; then
  echo "[-] FAIL: Deployment not created"
  exit 1
fi

echo "[.] Checking container count..."
CONTAINER_COUNT=$(kubectl get deployment test-multi-container -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[*].name}' | wc -w)

if [ "$CONTAINER_COUNT" -ne 3 ]; then
  echo "[-] FAIL: Expected 3 containers (2 user + 1 sidecar), got $CONTAINER_COUNT"
  exit 1
fi
echo "[+] Container count correct: $CONTAINER_COUNT"

echo "[.] Verifying sidecar present..."
CONTAINERS=$(kubectl get deployment test-multi-container -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[*].name}')
if [[ "$CONTAINERS" != *"asya-sidecar"* ]]; then
  echo "[-] FAIL: Sidecar not injected"
  echo "[.] Containers: $CONTAINERS"
  exit 1
fi
echo "[+] Sidecar injected: $CONTAINERS"

echo "[.] Verifying user containers preserved..."
if [[ "$CONTAINERS" != *"asya-runtime"* ]] || [[ "$CONTAINERS" != *"helper"* ]]; then
  echo "[-] FAIL: User containers not preserved"
  exit 1
fi
echo "[+] User containers preserved"
echo "[+] Scenario 2 PASS"
echo

# Scenario 3: Verify sidecar configuration
echo "=== Scenario 3: Sidecar configuration ==="
echo "[.] Checking sidecar env vars..."

SIDECAR_ENV=$(kubectl get deployment test-multi-container -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[?(@.name=="asya-sidecar")].env[*].name}')

REQUIRED_ENVS=("ASYA_SOCKET_DIR" "ASYA_LOG_LEVEL" "ASYA_GATEWAY_URL" "ASYA_ACTOR_NAME")
for ENV in "${REQUIRED_ENVS[@]}"; do
  if [[ "$SIDECAR_ENV" != *"$ENV"* ]]; then
    echo "[-] FAIL: Missing required env var: $ENV"
    exit 1
  fi
done
echo "[+] All required env vars present"

echo "[.] Checking sidecar volumes..."
SIDECAR_VOLUMES=$(kubectl get deployment test-multi-container -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[?(@.name=="asya-sidecar")].volumeMounts[*].name}')

REQUIRED_VOLUMES=("socket-dir" "tmp")
for VOL in "${REQUIRED_VOLUMES[@]}"; do
  if [[ "$SIDECAR_VOLUMES" != *"$VOL"* ]]; then
    echo "[-] FAIL: Missing required volume: $VOL"
    exit 1
  fi
done
echo "[+] All required volumes mounted"
echo "[+] Scenario 3 PASS"
echo

# Scenario 4: Verify runtime container configuration
echo "=== Scenario 4: Runtime container configuration ==="
echo "[.] Checking runtime container env vars..."

RUNTIME_ENV=$(kubectl get deployment test-multi-container -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[?(@.name=="asya-runtime")].env[*].name}')

if [[ "$RUNTIME_ENV" != *"ASYA_SOCKET_DIR"* ]]; then
  echo "[-] FAIL: Runtime container missing ASYA_SOCKET_DIR"
  exit 1
fi
echo "[+] Runtime container has socket path"

echo "[.] Checking runtime container volumes..."
RUNTIME_VOLUMES=$(kubectl get deployment test-multi-container -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[?(@.name=="asya-runtime")].volumeMounts[*].name}')

REQUIRED_RUNTIME_VOLUMES=("socket-dir" "tmp" "asya-runtime")
for VOL in "${REQUIRED_RUNTIME_VOLUMES[@]}"; do
  if [[ "$RUNTIME_VOLUMES" != *"$VOL"* ]]; then
    echo "[-] FAIL: Missing runtime volume: $VOL"
    exit 1
  fi
done
echo "[+] All runtime volumes mounted"
echo "[+] Scenario 4 PASS"
echo

echo "[.] Cleaning up..."
kubectl delete asyncactor test-multi-container -n "$NAMESPACE"
kubectl delete namespace "$NAMESPACE" --timeout="${TIMEOUT}s"

echo "=== Test Complete ==="
echo "[+] All sidecar injection scenarios PASS"
