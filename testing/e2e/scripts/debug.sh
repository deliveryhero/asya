#!/usr/bin/env bash
# E2E debugging tool - show diagnostics and/or logs for Asya components
#
# This script provides comprehensive debugging capabilities for the E2E test environment.
# It can display component status, deployment health, and recent logs from all Asya components.
#
# Usage:
#   ./debug.sh diagnostics   - Show component status, deployments, and events
#   ./debug.sh logs          - Show recent logs from all components
#   ./debug.sh both          - Show both diagnostics and logs
#
# Or via Makefile:
#   make diagnostics     - Run diagnostics only
#   make logs            - Show logs only
#
# Environment Variables:
#   NAMESPACE         - K8s namespace for Asya components (default: e2e)
#   SYSTEM_NAMESPACE  - K8s namespace for operator (default: asya-system)
#   CLUSTER_NAME      - Kind cluster name (default: asya-e2e-{profile})
#   TAIL              - Number of log lines for main components (default: 50)
#   ACTOR_TAIL        - Number of log lines for actors (default: 20)
#
# Components monitored:
#   - Asya Operator (deployment and pods)
#   - Asya Gateway (deployment and pods)
#   - RabbitMQ (statefulset and pods)
#   - PostgreSQL (statefulset and pods)
#   - Test Actors (dynamically discovered from AsyncActor CRDs)
#   - KEDA ScaledObjects
#   - AsyncActor CRDs
#   - Kubernetes Events

set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-asya-e2e-${PROFILE}}" # PROFILE is requied
SYSTEM_NAMESPACE="${SYSTEM_NAMESPACE:-asya-system}"
NAMESPACE="${NAMESPACE:-asya-e2e}"
TAIL="${TAIL:-50}"
ACTOR_TAIL="${ACTOR_TAIL:-20}"

# Parse command line arguments
SHOW_DIAGNOSTICS=false
SHOW_LOGS=false

if [ $# -eq 0 ]; then
  echo "Usage: $0 [diagnostics|logs|both]"
  echo
  echo "Options:"
  echo "  diagnostics  Show component status, deployments, and events"
  echo "  logs         Show recent logs from all components"
  echo "  both         Show both diagnostics and logs"
  echo
  echo "Environment variables:"
  echo "  NAMESPACE=$NAMESPACE"
  echo "  SYSTEM_NAMESPACE=$SYSTEM_NAMESPACE"
  echo "  CLUSTER_NAME=$CLUSTER_NAME"
  echo "  TAIL=$TAIL (main components)"
  echo "  ACTOR_TAIL=$ACTOR_TAIL (test actors)"
  exit 1
fi

for arg in "$@"; do
  case "$arg" in
    diagnostics)
      SHOW_DIAGNOSTICS=true
      ;;
    logs)
      SHOW_LOGS=true
      ;;
    both)
      SHOW_DIAGNOSTICS=true
      SHOW_LOGS=true
      ;;
    *)
      echo "Unknown argument: $arg"
      echo "Usage: $0 [diagnostics|logs|both]"
      exit 1
      ;;
  esac
done

# =============================================================================
# DIAGNOSTICS
# =============================================================================

show_diagnostics() {
  echo "=== Asya E2E Diagnostics ==="
  echo "Cluster: $CLUSTER_NAME"
  echo "Namespace: $NAMESPACE"
  echo "System Namespace: $SYSTEM_NAMESPACE"
  echo

  # Check if cluster exists
  if ! kind get clusters 2> /dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo "[-] Cluster '$CLUSTER_NAME' not found"
    return 1
  fi

  echo "[+] Cluster '$CLUSTER_NAME' exists"
  echo

  # Operator status
  echo "=== Operator Status ==="
  kubectl get deployment -n "$SYSTEM_NAMESPACE" -l app.kubernetes.io/name=asya-operator -o wide 2> /dev/null || echo "[!] Operator deployment not found"
  kubectl get pods -n "$SYSTEM_NAMESPACE" -l app.kubernetes.io/name=asya-operator -o wide 2> /dev/null || echo "[!] Operator pods not found"
  echo

  # Gateway status
  echo "=== Gateway Status ==="
  kubectl get deployment asya-gateway -n "$NAMESPACE" -o wide 2> /dev/null || echo "[!] Gateway deployment not found"
  kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=asya-gateway -o wide 2> /dev/null || echo "[!] Gateway pods not found"
  echo

  # RabbitMQ status
  echo "=== RabbitMQ Status ==="
  kubectl get statefulset asya-rabbitmq -n "$NAMESPACE" -o wide 2> /dev/null || echo "[!] RabbitMQ statefulset not found"
  kubectl get pods -n "$NAMESPACE" -l app=rabbitmq -o wide 2> /dev/null || echo "[!] RabbitMQ pods not found"
  echo

  # PostgreSQL status
  echo "=== PostgreSQL Status ==="
  kubectl get statefulset asya-gateway-postgresql -n "$NAMESPACE" -o wide 2> /dev/null || echo "[!] PostgreSQL statefulset not found"
  kubectl get pods -n "$NAMESPACE" -l app=postgresql -o wide 2> /dev/null || echo "[!] PostgreSQL pods not found"
  echo

  # Actor deployments (discover from AsyncActor CRDs)
  echo "=== Actor Deployments ==="
  local actors
  actors=$(kubectl get asyncactor -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}' 2> /dev/null || echo "")

  if [ -n "$actors" ]; then
    for actor in $actors; do
      echo "--- $actor ---"
      kubectl get deployment "$actor" -n "$NAMESPACE" -o wide 2> /dev/null || echo "[!] $actor deployment not found"
      kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name="$actor" -o wide 2> /dev/null || echo "[!] $actor pods not found"
      echo
    done
  else
    echo "[!] No AsyncActor CRDs found in namespace $NAMESPACE"
    echo
  fi

  # ScaledObjects (KEDA)
  echo "=== KEDA ScaledObjects ==="
  kubectl get scaledobject -n "$NAMESPACE" -o wide 2> /dev/null || echo "[!] No ScaledObjects found"
  echo

  # AsyncActor CRDs
  echo "=== AsyncActor CRDs ==="
  kubectl get asyncactor -n "$NAMESPACE" -o wide 2> /dev/null || echo "[!] No AsyncActors found"
  echo

  # Recent events
  echo "=== Recent Events (last 20) ==="
  kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' 2> /dev/null | tail -20 || echo "[!] No events found"
  echo

  echo "=== Diagnostics Complete ==="
}

# =============================================================================
# LOGS
# =============================================================================

show_logs() {
  echo "=== Asya Component Logs ==="
  echo

  # Operator logs
  echo "=== Operator Logs (tail=$TAIL) ==="
  kubectl logs -n "$SYSTEM_NAMESPACE" -l app.kubernetes.io/name=asya-operator --tail="$TAIL" 2> /dev/null || echo "[!] No operator logs"
  echo

  # Gateway logs
  echo "=== Gateway Logs (tail=$TAIL) ==="
  kubectl logs -n "$NAMESPACE" -l app.kubernetes.io/name=asya-gateway --tail="$TAIL" 2> /dev/null || echo "[!] No gateway logs"
  echo

  # RabbitMQ logs
  echo "=== RabbitMQ Logs (tail=$TAIL) ==="
  kubectl logs -n "$NAMESPACE" -l app=rabbitmq --tail="$TAIL" 2> /dev/null || echo "[!] No RabbitMQ logs"
  echo

  # PostgreSQL logs
  echo "=== PostgreSQL Logs (tail=$TAIL) ==="
  kubectl logs -n "$NAMESPACE" -l app=postgresql --tail="$TAIL" 2> /dev/null || echo "[!] No PostgreSQL logs"
  echo

  # Test actor logs (discover from AsyncActor CRDs)
  echo "=== Test Actor Logs (tail=$ACTOR_TAIL) ==="
  local actors
  actors=$(kubectl get asyncactor -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}' 2> /dev/null || echo "")

  if [ -n "$actors" ]; then
    for actor in $actors; do
      echo "--- $actor ---"
      kubectl logs -n "$NAMESPACE" -l app.kubernetes.io/name="$actor" --tail="$ACTOR_TAIL" 2> /dev/null || echo "[!] No logs for $actor"
      echo
    done
  else
    echo "[!] No AsyncActor CRDs found in namespace $NAMESPACE"
    echo
  fi

  echo "=== End of Logs ==="
}

# =============================================================================
# MAIN
# =============================================================================

if [ "$SHOW_DIAGNOSTICS" = true ]; then
  show_diagnostics
  echo
fi

if [ "$SHOW_LOGS" = true ]; then
  show_logs
fi
