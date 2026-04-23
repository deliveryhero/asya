#!/usr/bin/env bash
set -euo pipefail

# Deploy asya infrastructure + text-improver example to a k3d cluster.
# Expects: k3d cluster already running (created by `make cluster-up`)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GIT_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

CLUSTER_NAME="${CLUSTER_NAME:-asya-samples-e2e}"
REGISTRY_NAME="${REGISTRY_NAME:-asya-samples-registry}"
REGISTRY_PORT="${REGISTRY_PORT:-5111}"
NAMESPACE="${NAMESPACE:-asya-samples}"
SYSTEM_NAMESPACE="${SYSTEM_NAMESPACE:-asya-system}"

ASYA_CHART_REPO="https://asya.sh"
ASYA_REGISTRY="ghcr.io/deliveryhero"

echo "=== Asya Samples E2E Deploy ==="
echo "  cluster:   $CLUSTER_NAME"
echo "  namespace: $NAMESPACE"
echo "  registry:  localhost:$REGISTRY_PORT"

# --- Phase 1: Namespaces ---
echo "[.] Creating namespaces..."
kubectl create namespace "$SYSTEM_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# --- Phase 2: Crossplane ---
echo "[.] Installing Crossplane..."
helm repo add crossplane-stable https://charts.crossplane.io/stable --force-update
helm upgrade --install crossplane crossplane-stable/crossplane \
  --namespace "$SYSTEM_NAMESPACE" \
  --set args='{"--max-reconcile-rate=50","--poll-interval=10s"}' \
  --wait --timeout 120s

# --- Phase 3: KEDA ---
echo "[.] Installing KEDA..."
helm repo add kedacore https://kedacore.github.io/charts --force-update
helm upgrade --install keda kedacore/keda \
  --namespace "$SYSTEM_NAMESPACE" \
  --wait --timeout 120s

# --- Phase 4: RabbitMQ (minimal pod, no helm chart overhead) ---
echo "[.] Installing RabbitMQ..."
kubectl apply -n "$NAMESPACE" -f - << 'RABBITMQ'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rabbitmq
spec:
  replicas: 1
  selector:
    matchLabels: {app: rabbitmq}
  template:
    metadata:
      labels: {app: rabbitmq}
    spec:
      containers:
      - name: rabbitmq
        image: rabbitmq:3-management-alpine
        ports:
        - containerPort: 5672
        - containerPort: 15672
        env:
        - name: RABBITMQ_DEFAULT_USER
          value: guest
        - name: RABBITMQ_DEFAULT_PASS
          value: guest
        resources:
          requests: {memory: 128Mi, cpu: 100m}
          limits: {memory: 256Mi}
---
apiVersion: v1
kind: Service
metadata:
  name: rabbitmq
spec:
  selector: {app: rabbitmq}
  ports:
  - name: amqp
    port: 5672
  - name: management
    port: 15672
RABBITMQ
kubectl wait -n "$NAMESPACE" deployment/rabbitmq --for=condition=Available --timeout=120s

# --- Phase 5: PostgreSQL (minimal pod) ---
echo "[.] Installing PostgreSQL..."
kubectl apply -n "$NAMESPACE" -f - << 'POSTGRES'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgresql
spec:
  replicas: 1
  selector:
    matchLabels: {app: postgresql}
  template:
    metadata:
      labels: {app: postgresql}
    spec:
      containers:
      - name: postgresql
        image: postgres:16-alpine
        ports:
        - containerPort: 5432
        env:
        - name: POSTGRES_PASSWORD
          value: postgres
        - name: POSTGRES_DB
          value: asya
        resources:
          requests: {memory: 64Mi, cpu: 50m}
          limits: {memory: 128Mi}
---
apiVersion: v1
kind: Service
metadata:
  name: postgresql
spec:
  selector: {app: postgresql}
  ports:
  - port: 5432
POSTGRES
kubectl wait -n "$NAMESPACE" deployment/postgresql --for=condition=Available --timeout=120s

# --- Phase 6: Asya charts ---
echo "[.] Installing Asya components from $ASYA_CHART_REPO..."
helm repo add asya "$ASYA_CHART_REPO" --force-update

echo "  [.] asya-crossplane..."
helm upgrade --install asya-crossplane asya/asya-crossplane \
  --namespace "$SYSTEM_NAMESPACE" \
  --set sidecar.image.repository="${ASYA_REGISTRY}/asya-sidecar" \
  --set sidecar.image.tag=latest \
  --set sidecar.transport=rabbitmq \
  --set sidecar.rabbitmq.url="amqp://guest:guest@rabbitmq.${NAMESPACE}.svc.cluster.local:5672/" \
  --wait --timeout 180s

echo "  [.] asya-crew..."
helm upgrade --install asya-crew asya/asya-crew \
  --namespace "$NAMESPACE" \
  --set image.repository="${ASYA_REGISTRY}/asya-crew" \
  --set image.tag=latest \
  --set transport=rabbitmq \
  --set rabbitmq.url="amqp://guest:guest@rabbitmq.${NAMESPACE}.svc.cluster.local:5672/" \
  --wait --timeout 120s

echo "  [.] asya-gateway..."
helm upgrade --install asya-gateway asya/asya-gateway \
  --namespace "$NAMESPACE" \
  --set image.repository="${ASYA_REGISTRY}/asya-gateway" \
  --set image.tag=latest \
  --set gateway.transport=rabbitmq \
  --set gateway.rabbitmq.url="amqp://guest:guest@rabbitmq.${NAMESPACE}.svc.cluster.local:5672/" \
  --set gateway.database.url="postgres://postgres:postgres@postgresql.${NAMESPACE}.svc.cluster.local:5432/asya?sslmode=disable" \
  --wait --timeout 120s

# --- Phase 7: Wait for Crossplane providers ---
echo "[.] Waiting for Crossplane providers..."
kubectl wait --for=condition=Healthy provider.pkg.crossplane.io --all \
  --timeout=180s 2> /dev/null || echo "[!] No Crossplane providers to wait for (OK for minimal setup)"

# --- Phase 8: Build and push text-improver ---
echo "[.] Building text-improver image..."
REGISTRY_URL="localhost:${REGISTRY_PORT}"
docker build -t "${REGISTRY_URL}/asya-samples-text-improver:latest" "$REPO_ROOT/src/text-improver"
docker push "${REGISTRY_URL}/asya-samples-text-improver:latest"

# --- Phase 9: Compile and apply text-improver manifests ---
echo "[.] Compiling text-improver flow..."
cd "$REPO_ROOT"
PYTHONPATH="src:${PYTHONPATH:-}" uv run \
  --with "asya-lab @ file://${GIT_ROOT}/src/asya-lab" \
  asya compile flow_text_improver -f src/text-improver/flows/flow_text_improver.py

echo "[.] Applying text-improver manifests..."
# Patch image in manifests to use k3d registry
for f in .asya/flows/flow_text_improver/manifests/base/asya-actor-*.yaml; do
  [ -f "$f" ] || continue
  sed -i "s|image:.*|image: ${REGISTRY_URL}/asya-samples-text-improver:latest|" "$f"
done

kubectl apply -k .asya/flows/flow_text_improver/manifests/base/ -n "$NAMESPACE"

# --- Phase 10: Wait for actors ---
echo "[.] Waiting for AsyncActors..."
for _ in $(seq 1 30); do
  ready=$(kubectl get asyncactors -n "$NAMESPACE" -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' 2> /dev/null | grep -c "True" || true)
  total=$(kubectl get asyncactors -n "$NAMESPACE" --no-headers 2> /dev/null | wc -l || echo 0)
  if [ "$total" -gt 0 ] && [ "$ready" -eq "$total" ]; then
    echo "[+] All $total AsyncActors ready"
    break
  fi
  echo "  waiting... ($ready/$total ready)"
  sleep 10 # polling for k8s resource readiness
done

echo "[+] Deploy complete"
