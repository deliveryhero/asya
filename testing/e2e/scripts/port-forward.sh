#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-asya-e2e}"
ACTION="${1:-start}"

stop_port_forwards() {
  echo "Stopping port-forwards..."
  pkill -f "kubectl port-forward.*asya-gateway.*8080" 2> /dev/null || true
  pkill -f "kubectl port-forward.*svc/localstack-s3" 2> /dev/null || true
  pkill -f "kubectl port-forward.*svc/localstack-sqs" 2> /dev/null || true
  pkill -f "kubectl port-forward.*svc/asya-rabbitmq" 2> /dev/null || true
  pkill -f "kubectl port-forward.*svc/minio" 2> /dev/null || true
  echo "[+] Port-forwards stopped"
}

start_port_forwards() {
  echo "Setting up port-forwards for E2E testing..."

  # Forward gateway using asya-mcp-forward tool
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

  EXISTING_GATEWAY=$(pgrep -f "kubectl port-forward.*asya-gateway.*8080" || true)
  if [ -n "$EXISTING_GATEWAY" ]; then
    # Verify gateway port-forward is actually working
    if curl -s -f -m 2 http://localhost:8080/health > /dev/null 2>&1; then
      echo "[+] Gateway port-forward already running and healthy (localhost:8080)"
      echo "    PID: $EXISTING_GATEWAY"
    else
      echo "[!] Gateway port-forward PID exists but not responding, restarting..."
      pkill -f "kubectl port-forward.*asya-gateway" 2> /dev/null || true
      sleep 1
      nohup uv run --directory "$REPO_ROOT/src/asya-tools" asya-mcp-forward \
        --namespace "$NAMESPACE" \
        --deployment asya-gateway \
        --local-port 8080 \
        --port 8080 \
        --keep-alive > /dev/null 2>&1 &
      PF_GATEWAY=$!
      echo "[+] Gateway port-forward restarted (localhost:8080)"
      echo "    PID: $PF_GATEWAY"
      sleep 2
    fi
  else
    pkill -f "kubectl port-forward.*asya-gateway" 2> /dev/null || true
    nohup uv run --directory "$REPO_ROOT/src/asya-tools" asya-mcp-forward \
      --namespace "$NAMESPACE" \
      --deployment asya-gateway \
      --local-port 8080 \
      --port 8080 \
      --keep-alive > /dev/null 2>&1 &
    PF_GATEWAY=$!
    echo "[+] Gateway port-forward started (localhost:8080)"
    echo "    PID: $PF_GATEWAY"
    sleep 2
  fi

  # Forward S3 if present (for S3 storage tests)
  # Use port 4567 for S3 when both S3 and SQS exist, otherwise use 4566
  S3_LOCAL_PORT=4566
  if kubectl get svc -n "$NAMESPACE" localstack-s3 > /dev/null 2>&1 && kubectl get svc -n "$NAMESPACE" localstack-sqs > /dev/null 2>&1; then
    S3_LOCAL_PORT=4567
  fi

  if kubectl get svc -n "$NAMESPACE" localstack-s3 > /dev/null 2>&1; then
    EXISTING_S3=$(pgrep -f "kubectl port-forward.*svc/localstack-s3.*$S3_LOCAL_PORT" || true)
    if [ -n "$EXISTING_S3" ]; then
      echo "[+] S3 port-forward already running (localhost:$S3_LOCAL_PORT)"
      echo "    PID: $EXISTING_S3"
    else
      pkill -f "kubectl port-forward.*svc/localstack-s3" 2> /dev/null || true
      nohup kubectl port-forward -n "$NAMESPACE" svc/localstack-s3 $S3_LOCAL_PORT:4566 > /dev/null 2>&1 &
      PF_S3=$!
      echo "[+] S3 port-forward started (localhost:$S3_LOCAL_PORT)"
      echo "    PID: $PF_S3"
    fi
  fi

  # Forward SQS if present
  if kubectl get svc -n "$NAMESPACE" localstack-sqs > /dev/null 2>&1; then
    EXISTING_SQS=$(pgrep -f "kubectl port-forward.*svc/localstack-sqs.*4566" || true)
    if [ -n "$EXISTING_SQS" ]; then
      echo "[+] SQS port-forward already running (localhost:4566)"
      echo "    PID: $EXISTING_SQS"
    else
      pkill -f "kubectl port-forward.*svc/localstack-sqs" 2> /dev/null || true
      nohup kubectl port-forward -n "$NAMESPACE" svc/localstack-sqs 4566:4566 > /dev/null 2>&1 &
      PF_SQS=$!
      echo "[+] SQS port-forward started (localhost:4566)"
      echo "    PID: $PF_SQS"
    fi
  fi

  # Forward RabbitMQ if present (AMQP only, management port may not be enabled)
  if kubectl get svc -n "$NAMESPACE" asya-rabbitmq > /dev/null 2>&1; then
    EXISTING_RABBITMQ=$(pgrep -f "kubectl port-forward.*svc/asya-rabbitmq.*5672" || true)
    if [ -n "$EXISTING_RABBITMQ" ]; then
      echo "[+] RabbitMQ port-forward already running (localhost:5672)"
      echo "    PID: $EXISTING_RABBITMQ"
    else
      pkill -f "kubectl port-forward.*svc/asya-rabbitmq" 2> /dev/null || true
      nohup kubectl port-forward -n "$NAMESPACE" svc/asya-rabbitmq 5672:5672 > /dev/null 2>&1 &
      PF_RABBITMQ=$!
      echo "[+] RabbitMQ port-forward started (localhost:5672 AMQP)"
      echo "    PID: $PF_RABBITMQ"
    fi
  fi

  # Forward MinIO if present
  if kubectl get svc -n "$NAMESPACE" minio > /dev/null 2>&1; then
    EXISTING_MINIO=$(pgrep -f "kubectl port-forward.*svc/minio.*9000" || true)
    if [ -n "$EXISTING_MINIO" ]; then
      echo "[+] MinIO port-forward already running (localhost:9000)"
      echo "    PID: $EXISTING_MINIO"
    else
      pkill -f "kubectl port-forward.*svc/minio" 2> /dev/null || true
      nohup kubectl port-forward -n "$NAMESPACE" svc/minio 9000:9000 > /dev/null 2>&1 &
      PF_MINIO=$!
      echo "[+] MinIO port-forward started (localhost:9000)"
      echo "    PID: $PF_MINIO"
    fi
  fi
}

case "$ACTION" in
  start)
    start_port_forwards
    ;;
  stop)
    stop_port_forwards
    ;;
  *)
    echo "Usage: $0 {start|stop}"
    exit 1
    ;;
esac
