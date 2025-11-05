#!/bin/bash

# Port-forward Grafana for local access
# Usage: ./scripts/port-forward-grafana.sh [LOCAL_PORT]

set -euo pipefail

LOCAL_PORT="${1:-3000}"
NAMESPACE="monitoring"
SERVICE="grafana"
SERVICE_PORT="80"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}[INFO]${NC} Starting port-forward for Grafana..."
echo -e "${BLUE}[INFO]${NC} Namespace: ${NAMESPACE}"
echo -e "${BLUE}[INFO]${NC} Service: ${SERVICE}"
echo -e "${BLUE}[INFO]${NC} Local port: ${LOCAL_PORT}"
echo ""

# Check if service exists
if ! kubectl get svc "${SERVICE}" -n "${NAMESPACE}" &>/dev/null; then
    echo -e "${YELLOW}[WARN]${NC} Service '${SERVICE}' not found in namespace '${NAMESPACE}'"
    echo -e "${YELLOW}[WARN]${NC} Make sure Grafana is deployed"
    exit 1
fi

# Get Grafana credentials
echo -e "${BLUE}[INFO]${NC} Retrieving Grafana credentials..."
GRAFANA_USER="admin"
GRAFANA_PASSWORD=$(kubectl get secret -n "${NAMESPACE}" grafana -o jsonpath="{.data.admin-password}" 2>/dev/null | base64 --decode || echo "admin")

echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}Grafana Access Information${NC}"
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}URL:${NC}      http://localhost:${LOCAL_PORT}"
echo -e "${GREEN}Username:${NC} ${GRAFANA_USER}"
echo -e "${GREEN}Password:${NC} ${GRAFANA_PASSWORD}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo -e "${BLUE}[INFO]${NC} Port-forwarding will start now..."
echo -e "${BLUE}[INFO]${NC} Press Ctrl+C to stop"
echo ""

# Start port-forward
kubectl port-forward -n "${NAMESPACE}" "svc/${SERVICE}" "${LOCAL_PORT}:${SERVICE_PORT}"
