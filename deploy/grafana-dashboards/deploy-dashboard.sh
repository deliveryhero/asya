#!/bin/bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-monitoring}"
FOLDER="${GRAFANA_FOLDER:-Asya}"

if [ $# -eq 0 ]; then
  echo "Usage: $0 <dashboard-file.json> [configmap-name]"
  echo
  echo "Examples:"
  echo "  $0 asya-actors-overview.json"
  echo "  $0 asya-actors-overview.json asya-dashboard"
  echo
  echo "Environment variables:"
  echo "  NAMESPACE        - Kubernetes namespace (default: monitoring)"
  echo "  GRAFANA_FOLDER   - Grafana folder name (default: Asya)"
  exit 1
fi

DASHBOARD_FILE="$1"
CONFIGMAP_NAME="${2:-asya-dashboard}"

if [ ! -f "$DASHBOARD_FILE" ]; then
  echo "[!] Error: Dashboard file not found: $DASHBOARD_FILE"
  exit 1
fi

echo "[+] Deploying dashboard to Grafana..."
echo "    Dashboard file: $DASHBOARD_FILE"
echo "    ConfigMap name: $CONFIGMAP_NAME"
echo "    Namespace:      $NAMESPACE"
echo "    Grafana folder: $FOLDER"
echo

kubectl create configmap "$CONFIGMAP_NAME" \
  -n "$NAMESPACE" \
  --from-file=asya-actors.json="$DASHBOARD_FILE" \
  --dry-run=client -o yaml |
  kubectl label -f - --local \
    grafana_dashboard=1 \
    grafana_folder="$FOLDER" \
    -o yaml |
  kubectl apply -f -

echo
echo "[+] Dashboard deployed successfully!"
echo "[+] Grafana will automatically discover and load it within 30 seconds"
echo
echo "To access the dashboard:"
echo "  1. Port-forward Grafana: kubectl port-forward -n $NAMESPACE svc/prometheus-grafana 3000:80"
echo "  2. Open: http://localhost:3000"
echo "  3. Navigate to: Dashboards → $FOLDER folder"
