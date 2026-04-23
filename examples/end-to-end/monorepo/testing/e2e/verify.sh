#!/usr/bin/env bash
set -euo pipefail

# Verify that deployed actors are healthy.

NAMESPACE="${NAMESPACE:-asya-samples}"
FAILED=0

echo "=== Asya Samples E2E Verification ==="

# --- Check AsyncActors ---
echo "[.] Checking AsyncActors..."
total=$(kubectl get asyncactors -n "$NAMESPACE" --no-headers 2> /dev/null | wc -l || echo 0)
if [ "$total" -eq 0 ]; then
  echo "[-] No AsyncActors found in namespace $NAMESPACE"
  FAILED=1
else
  ready=$(kubectl get asyncactors -n "$NAMESPACE" -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' 2> /dev/null | grep -c "True" || true)
  if [ "$ready" -eq "$total" ]; then
    echo "[+] All $total AsyncActors are Ready"
  else
    echo "[-] Only $ready/$total AsyncActors are Ready"
    kubectl get asyncactors -n "$NAMESPACE" -o wide 2> /dev/null || true
    FAILED=1
  fi
fi

# --- Check Deployments ---
echo "[.] Checking Deployments..."
unavailable=$(kubectl get deployments -n "$NAMESPACE" -l asya.sh/flow \
  -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.availableReplicas}{"\n"}{end}' 2> /dev/null |
  awk '$2 == "" || $2 == 0 {print $1}' || true)

if [ -n "$unavailable" ]; then
  echo "[-] Deployments with no available replicas:"
  echo "${unavailable}" | while IFS= read -r line; do echo "    $line"; done
  FAILED=1
else
  deploy_count=$(kubectl get deployments -n "$NAMESPACE" -l asya.sh/flow --no-headers 2> /dev/null | wc -l || echo 0)
  echo "[+] All $deploy_count flow deployments have available replicas"
fi

# --- Check Pods ---
echo "[.] Checking Pods..."
not_running=$(kubectl get pods -n "$NAMESPACE" -l asya.sh/flow \
  --field-selector=status.phase!=Running,status.phase!=Succeeded \
  --no-headers 2> /dev/null | wc -l || echo 0)

if [ "$not_running" -gt 0 ]; then
  echo "[-] $not_running pods not Running:"
  kubectl get pods -n "$NAMESPACE" -l asya.sh/flow \
    --field-selector=status.phase!=Running,status.phase!=Succeeded 2> /dev/null || true
  FAILED=1
else
  pod_count=$(kubectl get pods -n "$NAMESPACE" -l asya.sh/flow --no-headers 2> /dev/null | wc -l || echo 0)
  echo "[+] All $pod_count flow pods are Running"
fi

# --- Summary ---
echo ""
if [ "$FAILED" -eq 1 ]; then
  echo "[-] Verification FAILED"
  echo ""
  echo "--- Diagnostics ---"
  kubectl get asyncactors -n "$NAMESPACE" -o wide 2> /dev/null || true
  echo ""
  kubectl get pods -n "$NAMESPACE" -o wide 2> /dev/null || true
  exit 1
else
  echo "[+] Verification PASSED"
fi
