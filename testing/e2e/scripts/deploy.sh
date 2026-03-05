#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHARTS_DIR="$SCRIPT_DIR/../charts"
REGISTRY="${REGISTRY:-ghcr.io/deliveryhero}"

# Set image prefix based on registry
if [[ -n "$REGISTRY" ]]; then
  IMAGE_PREFIX="${REGISTRY}/"
else
  IMAGE_PREFIX=""
fi

# Detect CPU cores for parallel operations
if command -v nproc > /dev/null 2>&1; then
  NCPU=$(nproc)
elif command -v sysctl > /dev/null 2>&1; then
  NCPU=$(sysctl -n hw.ncpu)
else
  NCPU=4
fi
CONCURRENCY="${CONCURRENCY:-$NCPU}"

# Parse arguments
RECREATE_CLUSTER=false
if [[ "${1:-}" == "--recreate" ]]; then
  RECREATE_CLUSTER=true
fi

# Validate profile
case "$PROFILE" in
  sqs-s3) ;;
  rabbitmq-minio) ;;
  pubsub-gcs) ;;
  *)
    echo "[!] Unknown profile: $PROFILE"
    echo "    Valid profiles: sqs-s3, rabbitmq-minio, pubsub-gcs"
    exit 1
    ;;
esac

CLUSTER_NAME="${CLUSTER_NAME:-asya-e2e-${PROFILE}}"
SYSTEM_NAMESPACE="${SYSTEM_NAMESPACE:-asya-system}"
NAMESPACE="${NAMESPACE:-asya-e2e}"

export HELMFILE_LOG_LEVEL="${HELMFILE_LOG_LEVEL:-error}"

echo "=== Asya Kind E2E Deployment Script (Crossplane) ==="
echo "Root directory: $ROOT_DIR"
echo "Charts directory: $CHARTS_DIR"
echo "Profile: $PROFILE"
echo "Cluster name: $CLUSTER_NAME"
echo "Namespace: $NAMESPACE (system: $SYSTEM_NAMESPACE)"
echo "Concurrency: $CONCURRENCY (CPUs: $NCPU)"
echo

# Check prerequisites
echo "[.] Checking prerequisites..."
command -v kind > /dev/null 2>&1 || {
  echo "Error: kind is not installed"
  exit 1
}
command -v kubectl > /dev/null 2>&1 || {
  echo "Error: kubectl is not installed"
  exit 1
}
command -v helm > /dev/null 2>&1 || {
  echo "Error: helm is not installed"
  exit 1
}
command -v helmfile > /dev/null 2>&1 || {
  echo "Error: helmfile is not installed"
  exit 1
}
command -v docker > /dev/null 2>&1 || {
  echo "Error: docker is not installed"
  exit 1
}
echo "[+] All prerequisites installed"
echo

# Phase 1: Create Kind cluster and build images in parallel
echo "[.] Phase 1: Setting up cluster and building components..."
time {
  # Start cluster creation
  CLUSTER_PID=""
  if kind get clusters 2> /dev/null | grep -q "^${CLUSTER_NAME}$"; then
    if [ "$RECREATE_CLUSTER" = true ]; then
      echo "[.] Deleting existing cluster..."
      kind delete cluster --name "$CLUSTER_NAME"
      kind create cluster --name "$CLUSTER_NAME" --config "$SCRIPT_DIR/../kind-config.yaml" &
      CLUSTER_PID=$!
    else
      echo "[!] Cluster '$CLUSTER_NAME' already exists, using existing cluster"
      echo "    (Use --recreate flag to delete and recreate)"
      kubectl config use-context "kind-${CLUSTER_NAME}"
    fi
  else
    echo "[.] Creating Kind cluster..."
    kind create cluster --name "$CLUSTER_NAME" --config "$SCRIPT_DIR/../kind-config.yaml" &
    CLUSTER_PID=$!
  fi

  # Build framework images (no operator needed)
  echo "[.] Building Docker images (gateway, sidecar, crew, testing)..."
  "$ROOT_DIR/src/build-images.sh" asya-gateway asya-sidecar asya-crew asya-testing &
  BUILD_PID=$!

  # Build injector image separately (not in build-images.sh registry)
  echo "[.] Building asya-injector image..."
  docker build -t "${IMAGE_PREFIX}asya-injector:latest" "$ROOT_DIR/src/asya-injector/" > /dev/null 2>&1 &
  INJECTOR_BUILD_PID=$!

  # Build Crossplane function image (will be pushed to local registry in Phase 3)
  echo "[.] Building function-asya-overlays image..."
  docker build -t "function-asya-overlays:latest" "$ROOT_DIR/src/function-asya-overlays/" > /dev/null 2>&1 &
  FUNCTION_BUILD_PID=$!

  # Build state-proxy connector image for the active profile
  if [[ "$PROFILE" == "sqs-s3" ]]; then
    echo "[.] Building state-proxy S3 connector image..."
    docker build -t "${IMAGE_PREFIX}asya-state-proxy-s3-buffered-lww:dev" \
      -f "$ROOT_DIR/src/asya-state-proxy/Dockerfile.s3-buffered-lww" \
      "$ROOT_DIR/src/asya-state-proxy/" > /dev/null 2>&1 &
    STATE_PROXY_BUILD_PID=$!
  elif [[ "$PROFILE" == "pubsub-gcs" ]]; then
    echo "[.] Building state-proxy GCS connector image..."
    docker build -t "${IMAGE_PREFIX}asya-state-proxy-gcs-buffered-lww:dev" \
      -f "$ROOT_DIR/src/asya-state-proxy/Dockerfile.gcs-buffered-lww" \
      "$ROOT_DIR/src/asya-state-proxy/" > /dev/null 2>&1 &
    STATE_PROXY_BUILD_PID=$!
  fi

  # Wait for image builds
  if ! wait "$BUILD_PID"; then
    echo "[-] Docker image build failed"
    exit 1
  fi
  echo "[+] Framework Docker images built"

  if ! wait "$INJECTOR_BUILD_PID"; then
    echo "[-] Injector image build failed"
    exit 1
  fi
  echo "[+] Injector image built"

  if ! wait "$FUNCTION_BUILD_PID"; then
    echo "[-] function-asya-overlays build failed"
    exit 1
  fi
  echo "[+] function-asya-overlays image built"

  if [[ -n "${STATE_PROXY_BUILD_PID:-}" ]]; then
    if ! wait "$STATE_PROXY_BUILD_PID"; then
      echo "[-] State-proxy connector image build failed"
      exit 1
    fi
    echo "[+] State-proxy connector image built"
  fi

  # Wait for cluster creation
  if [ -n "$CLUSTER_PID" ]; then
    if ! wait "$CLUSTER_PID"; then
      echo "[-] Kind cluster creation failed"
      exit 1
    fi
    kubectl config use-context "kind-${CLUSTER_NAME}"
    echo "[+] Kind cluster ready (context: kind-${CLUSTER_NAME})"
  fi
}
echo

# Phase 2: Install cluster-level infrastructure (cert-manager + Crossplane core)
echo "[.] Phase 2: Installing cluster-level infrastructure..."
time {
  echo "[.] Installing cert-manager..."
  kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.5/cert-manager.yaml > /dev/null 2>&1

  echo "[.] Installing Crossplane core..."
  helm repo add crossplane-stable https://charts.crossplane.io/stable --force-update > /dev/null 2>&1
  helm repo update crossplane-stable > /dev/null 2>&1
  helm upgrade --install crossplane crossplane-stable/crossplane \
    --namespace crossplane-system --create-namespace \
    --wait --timeout 120s > /dev/null 2>&1

  echo "[.] Waiting for cert-manager webhooks..."
  kubectl wait --for=condition=available deployment/cert-manager-webhook \
    -n cert-manager --timeout=120s > /dev/null 2>&1

  echo "[.] Waiting for Crossplane pods..."
  kubectl wait --for=condition=available deployment/crossplane \
    -n crossplane-system --timeout=120s > /dev/null 2>&1

  echo "[+] cert-manager and Crossplane core installed"
}
echo

# Phase 3: Load images into Kind cluster and set up local OCI registry
#
# Container images (sidecar, gateway, crew, etc.) are loaded via `kind load docker-image`
# into containerd's image store. Kubelet uses these with `imagePullPolicy: Never`.
#
# Crossplane Function packages (function-asya-overlays) use Crossplane's own OCI puller,
# NOT containerd — `kind load` does NOT work for them. We run a local OCI registry
# (registry:2), push freshly-built function images to it, and point the Crossplane
# Function CRD at the registry's cluster-internal IP. This lets E2E tests run on the
# same function-asya-overlays code that was just built, matching how other images work.
#
# Crossplane's OCI client (go-containerregistry) uses HTTPS by default. A plain HTTP
# registry at a private IP fails silently. We generate a self-signed TLS cert so the
# registry serves HTTPS, configure Docker to trust it for push, and configure
# Crossplane via registryCaBundleConfig to trust the CA for pull.
REGISTRY_NAME="${REGISTRY_NAME:-asya-e2e-registry}"
REGISTRY_HOST_PORT=5001
OVERLAYS_REPOSITORY=""
REGISTRY_CERTS_DIR=$(mktemp -d)

echo "[.] Phase 3: Loading images into Kind cluster..."
time {
  IMAGES_TO_LOAD=(
    "asya-gateway:latest"
    "asya-sidecar:latest"
    "asya-crew:latest"
    "asya-testing:latest"
    "asya-injector:latest"
  )

  if [[ "$PROFILE" == "sqs-s3" ]]; then
    IMAGES_TO_LOAD+=("asya-state-proxy-s3-buffered-lww:dev")
  elif [[ "$PROFILE" == "pubsub-gcs" ]]; then
    IMAGES_TO_LOAD+=("asya-state-proxy-gcs-buffered-lww:dev")
  fi

  LOAD_PIDS=()
  for img in "${IMAGES_TO_LOAD[@]}"; do
    kind load docker-image "${IMAGE_PREFIX}$img" --name "$CLUSTER_NAME" &
    LOAD_PIDS+=($!)
  done

  # Set up local OCI registry with TLS for Crossplane Function packages.
  # Crossplane's package manager runs inside a pod and uses HTTPS by default,
  # so the registry must serve TLS. We generate a self-signed CA + server cert
  # for the registry's Kind network IP.
  #
  # To avoid IP mismatch, we keep the SAME container throughout: start it on
  # the Kind network (HTTP), discover its IP, generate a TLS cert for that IP,
  # copy certs in via docker cp, update the config, and restart. docker restart
  # preserves network attachments and IP addresses.
  echo "[.] Setting up local OCI registry for Crossplane functions..."
  docker rm -f "$REGISTRY_NAME" 2> /dev/null || true

  # Start registry on the Kind network with host port mapping (HTTP initially)
  docker run -d --restart=always -p "${REGISTRY_HOST_PORT}:5000" \
    --name "$REGISTRY_NAME" --network kind registry:2 > /dev/null

  REGISTRY_IP=$(docker inspect -f '{{.NetworkSettings.Networks.kind.IPAddress}}' "$REGISTRY_NAME")
  if [ -z "$REGISTRY_IP" ]; then
    echo "[-] Failed to get IP address for local registry container '$REGISTRY_NAME'"
    exit 1
  fi

  # Generate self-signed TLS cert covering both the Kind network IP (for
  # Crossplane pulling from inside the cluster) and localhost (for Docker
  # pushing from the host).
  CERT_SAN="IP:${REGISTRY_IP},DNS:localhost,IP:127.0.0.1"
  echo "[.] Generating TLS certificate (SAN: ${CERT_SAN})..."
  openssl req -new -x509 -days 1 -nodes -newkey rsa:2048 \
    -keyout "$REGISTRY_CERTS_DIR/ca.key" -out "$REGISTRY_CERTS_DIR/ca.crt" \
    -subj "/CN=E2E Registry CA" 2> /dev/null
  openssl req -new -nodes -newkey rsa:2048 \
    -keyout "$REGISTRY_CERTS_DIR/server.key" -out "$REGISTRY_CERTS_DIR/server.csr" \
    -subj "/CN=${REGISTRY_IP}" \
    -addext "subjectAltName=${CERT_SAN}" 2> /dev/null
  openssl x509 -req -in "$REGISTRY_CERTS_DIR/server.csr" \
    -CA "$REGISTRY_CERTS_DIR/ca.crt" -CAkey "$REGISTRY_CERTS_DIR/ca.key" \
    -CAcreateserial -out "$REGISTRY_CERTS_DIR/server.crt" -days 1 \
    -extfile <(echo "subjectAltName=${CERT_SAN}") 2> /dev/null

  # Copy certs into the running container and enable TLS via config file.
  # docker restart preserves the container's network IP, avoiding the need
  # for --ip (which requires user-configured subnets).
  docker exec "$REGISTRY_NAME" mkdir -p /certs
  docker cp "$REGISTRY_CERTS_DIR/server.crt" "${REGISTRY_NAME}:/certs/server.crt"
  docker cp "$REGISTRY_CERTS_DIR/server.key" "${REGISTRY_NAME}:/certs/server.key"
  docker exec "$REGISTRY_NAME" sh -c 'cat > /etc/docker/registry/config.yml << YAML
version: 0.1
storage:
  filesystem:
    rootdirectory: /var/lib/registry
http:
  addr: :5000
  tls:
    certificate: /certs/server.crt
    key: /certs/server.key
YAML'
  docker restart "$REGISTRY_NAME" > /dev/null
  echo "[+] Registry restarted with TLS at ${REGISTRY_IP}:5000"

  # Configure Docker to trust the CA for localhost push
  DOCKER_CERT_DIR="/etc/docker/certs.d/localhost:${REGISTRY_HOST_PORT}"
  sudo mkdir -p "$DOCKER_CERT_DIR"
  sudo cp "$REGISTRY_CERTS_DIR/ca.crt" "$DOCKER_CERT_DIR/ca.crt"

  # Configure containerd on Kind nodes to trust the CA for runtime image pulls.
  # Crossplane creates Deployments that reference the registry image, so kubelet
  # needs containerd to trust our CA when pulling function runtime images.
  # kind-config.yaml sets config_path="/etc/containerd/certs.d", so containerd
  # discovers hosts.toml files dynamically. Fallback adds config_path + restarts
  # containerd if the cluster was created without the containerdConfigPatches.
  CONTAINERD_CERTS_DIR="/etc/containerd/certs.d/${REGISTRY_IP}:5000"
  for node in $(kind get nodes --name "$CLUSTER_NAME" 2> /dev/null); do
    docker cp "$REGISTRY_CERTS_DIR/ca.crt" "${node}:/root/registry-ca.crt"
    docker exec "$node" mkdir -p "$CONTAINERD_CERTS_DIR"
    docker exec "$node" cp /root/registry-ca.crt "${CONTAINERD_CERTS_DIR}/ca.crt"
    docker exec "$node" bash -c "cat > ${CONTAINERD_CERTS_DIR}/hosts.toml << TOML
server = \"https://${REGISTRY_IP}:5000\"

[host.\"https://${REGISTRY_IP}:5000\"]
  ca = \"${CONTAINERD_CERTS_DIR}/ca.crt\"
TOML"
    # Fallback: enable containerd registry host discovery if not already set
    if ! docker exec "$node" grep -q 'config_path.*certs.d' /etc/containerd/config.toml; then
      docker exec "$node" bash -c 'cat >> /etc/containerd/config.toml << TOML

[plugins."io.containerd.grpc.v1.cri".registry]
  config_path = "/etc/containerd/certs.d"
TOML'
      docker exec "$node" systemctl restart containerd
    fi
  done
  echo "[+] containerd CA trust configured on Kind nodes"

  # Push function image to the TLS registry
  docker tag "function-asya-overlays:latest" \
    "localhost:${REGISTRY_HOST_PORT}/function-asya-overlays:latest"
  docker push "localhost:${REGISTRY_HOST_PORT}/function-asya-overlays:latest" > /dev/null

  # Create ConfigMap with CA cert so Crossplane trusts the registry
  kubectl create configmap local-registry-ca \
    --from-file=ca-certificates.crt="$REGISTRY_CERTS_DIR/ca.crt" \
    -n crossplane-system --dry-run=client -o yaml | kubectl apply -f - > /dev/null

  # Reconfigure Crossplane to trust the local registry CA
  helm upgrade crossplane crossplane-stable/crossplane \
    -n crossplane-system --reuse-values \
    --set "registryCaBundleConfig.name=local-registry-ca" \
    --set "registryCaBundleConfig.key=ca-certificates.crt" \
    --wait --timeout 60s > /dev/null

  OVERLAYS_REPOSITORY="${REGISTRY_IP}:5000/function-asya-overlays"
  echo "[+] Local OCI registry (TLS) at ${REGISTRY_IP}:5000"
  echo "[+] Function repository: ${OVERLAYS_REPOSITORY}"

  # Wait for all kind load operations
  LOAD_FAILED=false
  for pid in "${LOAD_PIDS[@]}"; do
    if ! wait "$pid"; then
      LOAD_FAILED=true
    fi
  done

  if [ "$LOAD_FAILED" = true ]; then
    echo "[-] Failed to load one or more images into Kind cluster"
    exit 1
  fi

  echo "[+] Images loaded into Kind cluster"
}
echo

# Phase 4: Create prerequisite secrets
echo "[.] Phase 4: Creating prerequisite secrets..."
time {
  # Create namespaces if they don't exist
  kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
  kubectl create namespace "$SYSTEM_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1

  if [[ "$PROFILE" == "sqs-s3" ]]; then
    # AWS credentials for Crossplane provider (credentials file format)
    kubectl create secret generic aws-creds \
      -n crossplane-system \
      --from-literal=credentials="[default]
aws_access_key_id = test
aws_secret_access_key = test
" \
      --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    echo "[+] Created aws-creds secret in crossplane-system"

    # AWS credentials for KEDA TriggerAuthentication (key/value format)
    kubectl create secret generic aws-creds \
      -n "$NAMESPACE" \
      --from-literal=AWS_ACCESS_KEY_ID=test \
      --from-literal=AWS_SECRET_ACCESS_KEY=test \
      --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    echo "[+] Created aws-creds secret in $NAMESPACE"

    # sqs-secret in asya-system is created by the SQS Helm chart (testing/e2e/charts/sqs/)
    # Do NOT create it here — Helm requires ownership metadata on managed resources
  elif [[ "$PROFILE" == "pubsub-gcs" ]]; then
    # Generate a real RSA private key so the GCP auth library can sign the JWT assertion.
    # A placeholder key fails to parse, so the provider can never reach the mock OAuth server.
    # The mock OAuth server (mock-oauth.asya-system) accepts any POST and returns a dummy
    # Bearer token; the emulator then accepts that token without validation.
    GCP_KEY_FILE=$(mktemp)
    openssl genrsa 2048 > "$GCP_KEY_FILE" 2> /dev/null
    GCP_DUMMY_CREDS=$(
      python3 - "$GCP_KEY_FILE" << 'PYEOF'
import json, sys
key = open(sys.argv[1]).read()
print(json.dumps({
    "type": "service_account",
    "project_id": "test-project",
    "private_key_id": "test-key-id",
    "private_key": key,
    "client_email": "test@test-project.iam.gserviceaccount.com",
    "token_uri": "http://mock-oauth.asya-system.svc.cluster.local:8090/token",
}))
PYEOF
    )
    rm -f "$GCP_KEY_FILE"

    kubectl create secret generic gcp-creds \
      -n crossplane-system \
      --from-literal=credentials.json="$GCP_DUMMY_CREDS" \
      --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    echo "[+] Created gcp-creds secret in crossplane-system"

    kubectl create secret generic gcp-keda-secret \
      -n "$NAMESPACE" \
      --from-literal=credentials.json="$GCP_DUMMY_CREDS" \
      --dry-run=client -o yaml | kubectl apply -f - > /dev/null 2>&1
    echo "[+] Created gcp-keda-secret in $NAMESPACE"
  else
    echo "[.] Skipping cloud credentials (not needed for $PROFILE)"
  fi
}
echo

# Phase 5: Deploy infrastructure layer with Helmfile
echo "[.] Phase 5: Deploying infrastructure layer..."
time {
  cd "$CHARTS_DIR"
  if ! helmfile -f helmfile.yaml.gotmpl -e "$PROFILE" sync --concurrency "$CONCURRENCY" --selector 'layer=infra'; then
    echo "[-] Infrastructure deployment failed! Gathering diagnostics..."
    echo ""
    echo "=== Pod Status ==="
    kubectl get pods -n "$NAMESPACE" -o wide || true
    kubectl get pods -n "$SYSTEM_NAMESPACE" -o wide || true
    kubectl get pods -n crossplane-system -o wide || true
    kubectl get pods -n keda -o wide || true
    echo ""
    echo "=== Gateway Pod Events ==="
    kubectl get events -n "$NAMESPACE" --field-selector involvedObject.kind=Pod --sort-by='.lastTimestamp' | grep -i gateway || true
    echo ""
    echo "=== Gateway Pod Details ==="
    kubectl describe pod -n "$NAMESPACE" -l app.kubernetes.io/name=asya-gateway || true
    echo ""
    echo "=== Gateway Current Logs ==="
    kubectl logs -n "$NAMESPACE" -l app.kubernetes.io/name=asya-gateway --tail=100 --all-containers=true || true
    echo ""
    echo "=== Crossplane Provider Logs ==="
    kubectl logs -n crossplane-system -l pkg.crossplane.io/revision --tail=50 --all-containers=true || true
    echo ""
    echo "=== Injector Logs ==="
    kubectl logs -n "$SYSTEM_NAMESPACE" -l app.kubernetes.io/name=asya-injector --tail=50 || true
    echo ""
    echo "=== Migration Job Logs ==="
    kubectl logs -n "$NAMESPACE" -l app.kubernetes.io/component=migration --tail=50 || true
    exit 1
  fi
  echo "[+] Infrastructure layer deployed"
}
echo

# Point function-asya-overlays at the local OCI registry.
# Phase 5 created the Function CRD with the default ghcr.io URL; this upgrade
# rewrites the package field so Crossplane pulls from our local registry instead.
if [ -n "$OVERLAYS_REPOSITORY" ]; then
  echo "[.] Pointing function-asya-overlays at local registry..."
  helm upgrade asya-crossplane ../../../deploy/helm-charts/asya-crossplane \
    -n asya-system --reuse-values \
    --set "functions.overlaysRepository=${OVERLAYS_REPOSITORY}" \
    --set "functions.overlaysVersion=latest" \
    --set "functions.overlaysPackagePullPolicy=Always" \
    --wait --timeout 60s > /dev/null
  echo "[+] Function CRD updated: ${OVERLAYS_REPOSITORY}:latest"
fi
echo

# Phase 6: Wait for Crossplane providers to become healthy
echo "[.] Phase 6: Waiting for Crossplane providers to become healthy..."
time {
  echo "[.] Waiting for Crossplane providers..."
  if ! kubectl wait --for=condition=healthy providers.pkg.crossplane.io --all --timeout=300s 2> /dev/null; then
    echo "[!] Warning: Some Crossplane providers may not be healthy"
    kubectl get providers.pkg.crossplane.io || true
  else
    echo "[+] All Crossplane providers healthy"
  fi

  echo "[.] Waiting for Crossplane functions..."
  if ! kubectl wait --for=condition=healthy functions.pkg.crossplane.io --all --timeout=300s 2> /dev/null; then
    echo "[!] Warning: Some Crossplane functions may not be healthy"
    kubectl get functions.pkg.crossplane.io || true
  else
    echo "[+] All Crossplane functions healthy"
  fi
}
echo

# Phase 6b: Install ProviderConfigs (CRDs now available after providers are healthy)
echo "[.] Phase 6b: Installing Crossplane ProviderConfigs..."
time {
  cd "$CHARTS_DIR"
  helm upgrade asya-crossplane ../../../deploy/helm-charts/asya-crossplane \
    -n asya-system --reuse-values --set providerConfigs.install=true \
    --wait --timeout 120s > /dev/null 2>&1
  echo "[+] ProviderConfigs installed"
}
echo

# Phase 6c: Wait for asya-injector webhook TLS to be ready
# cert-manager's cainjector asynchronously injects the CA bundle into the
# MutatingWebhookConfiguration after the Certificate is issued. Without this
# wait, AsyncActor creation in Phase 7 fails with "x509: certificate signed
# by unknown authority" because the API server hasn't received the CA bundle yet.
echo "[.] Phase 6c: Waiting for asya-injector webhook TLS..."
time {
  echo "[.] Waiting for Certificate to be issued..."
  if ! kubectl wait --for=condition=Ready certificate/asya-injector-tls \
    -n "$SYSTEM_NAMESPACE" --timeout=120s 2> /dev/null; then
    echo "[-] Certificate not ready after 120s"
    kubectl get certificate -n "$SYSTEM_NAMESPACE" || true
    exit 1
  fi
  echo "[+] Certificate issued"

  echo "[.] Waiting for CA bundle injection into webhook..."
  for i in $(seq 1 30); do
    CA_BUNDLE=$(kubectl get mutatingwebhookconfiguration asya-injector \
      -o jsonpath='{.webhooks[0].clientConfig.caBundle}' 2> /dev/null)
    if [ -n "$CA_BUNDLE" ]; then
      echo "[+] CA bundle injected into MutatingWebhookConfiguration"
      break
    fi
    if [ "$i" -eq 30 ]; then
      echo "[-] Timeout waiting for CA bundle injection (60s)"
      kubectl get mutatingwebhookconfiguration asya-injector -o yaml || true
      exit 1
    fi
    sleep 2 # Poll for cainjector to update the webhook config
  done
}
echo

# Phase 7: Deploy application layer with Helmfile (test actors + system actors)
echo "[.] Phase 7: Deploying application layer (actors)..."
time {
  cd "$CHARTS_DIR"
  if ! helmfile -f helmfile.yaml.gotmpl -e "$PROFILE" sync --concurrency "$CONCURRENCY" --selector 'layer=app'; then
    echo "[-] Actor deployment failed! Gathering diagnostics..."
    echo ""
    echo "=== AsyncActor CRDs ==="
    kubectl get asyncactor -n "$NAMESPACE" || true
    echo ""
    echo "=== Actor Pod Status ==="
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=actor -o wide || true
    echo ""
    echo "=== Crossplane Provider Logs ==="
    kubectl logs -n crossplane-system -l pkg.crossplane.io/revision --tail=100 --all-containers=true || true
    echo ""
    echo "=== Injector Logs ==="
    kubectl logs -n "$SYSTEM_NAMESPACE" -l app.kubernetes.io/name=asya-injector --tail=100 || true
    echo ""
    echo "=== Failed Actor Pods (if any) ==="
    kubectl describe pods -n "$NAMESPACE" -l app.kubernetes.io/component=actor | grep -A 20 "State.*Waiting\|State.*Terminated" || true
    exit 1
  fi
  echo "[+] Application layer deployed"
}
echo

# Phase 8: Wait for Crossplane to reconcile all AsyncActor claims
echo "[.] Phase 8: Waiting for Crossplane to reconcile AsyncActor claims..."
time {
  if ! kubectl wait --for=condition=Ready asyncactor --all \
    -n "$NAMESPACE" --timeout=120s; then
    echo "[!] Warning: Not all AsyncActors reconciled"
    echo "[.] Current AsyncActor status:"
    kubectl get asyncactors -n "$NAMESPACE"
  else
    TOTAL_ACTORS=$(kubectl get asyncactors -n "$NAMESPACE" --no-headers 2> /dev/null | wc -l)
    echo "[+] All $TOTAL_ACTORS AsyncActors reconciled (condition=Ready)"
  fi
}
echo

# Phase 9: Wait for actor pods to scale up and be ready
echo "[.] Phase 9: Waiting for actor pods to be ready..."
time {
  # Give KEDA time to create HPAs and scale up pods
  sleep 2

  if ! kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/component=actor \
    -n "$NAMESPACE" \
    --timeout=120s 2> /dev/null; then
    echo "[!] Warning: Some actor pods may not be ready yet"
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=actor
  else
    READY_PODS=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=actor --field-selector=status.phase=Running --no-headers 2> /dev/null | wc -l)
    echo "[+] All $READY_PODS actor pods are ready"
  fi
}
echo

# Run Helm tests after Crossplane reconciliation and pod readiness.
# Helm tests verify the end state (labels, connectivity, schema) and need
# Deployments to exist, so they must run after Phase 8/9.
if [ "${SKIP_HELM_TESTS:-false}" = "true" ]; then
  echo "[!] Skipping Helm tests (SKIP_HELM_TESTS=true)"
  echo
else
  echo "[.] Running Helm tests..."
  time {
    cd "$CHARTS_DIR"

    HELM_TEST_TIMEOUT="${HELM_TEST_TIMEOUT:-300}"
    echo "[.] Helm test timeout: ${HELM_TEST_TIMEOUT}s"

    TEST_OUTPUT=$(helmfile -f helmfile.yaml.gotmpl -e "$PROFILE" test --concurrency "$CONCURRENCY" --timeout "$HELM_TEST_TIMEOUT" --logs 2>&1) || TEST_EXIT_CODE=$?
    echo "$TEST_OUTPUT"

    if [ "${TEST_EXIT_CODE:-0}" -ne 0 ]; then
      case "$TEST_OUTPUT" in
        *"Phase: "*"Failed"*)
          echo "[-] Helm tests failed! Gathering diagnostics..."
          echo ""

          echo "=== Helm Release Status ==="
          helm list -n "$NAMESPACE" || true
          helm list -n "$SYSTEM_NAMESPACE" || true
          echo ""

          echo "=== All Pods (including completed/failed) ==="
          kubectl get pods -n "$NAMESPACE" -o wide || true
          kubectl get pods -n "$SYSTEM_NAMESPACE" -o wide || true
          echo ""

          echo "=== Recent Events (namespace: $NAMESPACE) ==="
          kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' | tail -50 || true
          echo ""

          echo "=== Recent Events (namespace: $SYSTEM_NAMESPACE) ==="
          kubectl get events -n "$SYSTEM_NAMESPACE" --sort-by='.lastTimestamp' | tail -50 || true
          echo ""

          echo "=== Test Pod Logs (if still available) ==="
          for ns in "$NAMESPACE" "$SYSTEM_NAMESPACE"; do
            kubectl get pods -n "$ns" -l 'helm.sh/hook=test' -o name 2> /dev/null | while read -r pod; do
              [ -z "$pod" ] && continue
              echo "--- Logs from $pod (namespace: $ns) ---"
              kubectl logs -n "$ns" "$pod" --tail=100 || true
              echo ""
            done
          done

          echo "=== Crossplane Provider Logs ==="
          kubectl logs -n crossplane-system -l pkg.crossplane.io/revision --tail=100 --all-containers=true || true
          echo ""

          echo "=== GCP Managed Resources ==="
          kubectl get topics.pubsub.gcp.upbound.io -A 2> /dev/null || true
          kubectl get subscriptions.pubsub.gcp.upbound.io -A 2> /dev/null || true
          echo ""

          echo "=== GCP Managed Resource Conditions ==="
          kubectl get topics.pubsub.gcp.upbound.io -A -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.conditions[*]}{.type}={.status} ({.reason}: {.message}){" "}{end}{"\n"}{end}' 2> /dev/null | head -5 || true
          kubectl get subscriptions.pubsub.gcp.upbound.io -A -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.conditions[*]}{.type}={.status} ({.reason}: {.message}){" "}{end}{"\n"}{end}' 2> /dev/null | head -5 || true
          echo ""

          exit 1
          ;;
        *"unable to get pod logs"*"pods "*"not found"*)
          echo "[!] Helm test command failed trying to fetch logs from deleted test pods"
          echo "[.] Checking if all tests actually passed..."
          if [[ "$TEST_OUTPUT" == *"Phase: "*"Succeeded"* ]] && ! [[ "$TEST_OUTPUT" == *"Phase: "*"Failed"* ]]; then
            echo "[+] All tests passed (ignoring log fetch errors for deleted pods)"
          else
            echo "[-] Unable to determine test status, failing deployment"
            exit 1
          fi
          ;;
        *)
          echo "[-] Helm tests failed with unexpected error"
          exit 1
          ;;
      esac
    fi
    echo "[+] All Helm tests completed successfully"
    echo
  }
fi

# Phase 10: Print detailed component status and save logs
echo "[.] Phase 10: Running diagnostics..."
time {
  "$SCRIPT_DIR/debug.sh" diagnostics
}
echo

# Save logs to file for debugging
LOGS_DIR="$SCRIPT_DIR/../.logs"
mkdir -p "$LOGS_DIR"

INJECTOR_LOGS="$LOGS_DIR/injector-$(date +%Y%m%d-%H%M%S).log"
echo "[.] Saving injector logs to: $INJECTOR_LOGS"
kubectl logs -n "$SYSTEM_NAMESPACE" -l app.kubernetes.io/name=asya-injector --tail=1000 > "$INJECTOR_LOGS" 2>&1 || true

CROSSPLANE_LOGS="$LOGS_DIR/crossplane-$(date +%Y%m%d-%H%M%S).log"
echo "[.] Saving Crossplane provider logs to: $CROSSPLANE_LOGS"
kubectl logs -n crossplane-system -l pkg.crossplane.io/revision --tail=1000 --all-containers=true > "$CROSSPLANE_LOGS" 2>&1 || true

echo "[+] Logs saved"
echo

echo "=== Deployment Complete (Crossplane) ==="
echo "Injector logs saved to: $INJECTOR_LOGS"
echo "Crossplane logs saved to: $CROSSPLANE_LOGS"
echo ""
echo "Next steps (from the current directory):"
echo "$ make trigger-tests"
echo ""
