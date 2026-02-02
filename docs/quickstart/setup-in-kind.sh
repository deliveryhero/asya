#!/usr/bin/env bash
# Quick setup script for Asya🎭 in Kind cluster
#
# IMPORTANT: Keep this script in sync with docs/quickstart/README.md
# This script automates the manual steps documented in the README.
# When updating the README, verify this script still works correctly.
# When updating this script, update corresponding sections in README.
#
# Usage:
#   ./setup-in-kind.sh [OPTIONS]
#
# Options:
#   --full          Install all components (S3, Gateway, Prometheus)
#   --with-s3       Install S3 storage (crew actors)
#   --with-gateway  Install Gateway with PostgreSQL
#   --with-prometheus  Install Prometheus monitoring
#   --help          Show this help message
#
# Examples:
#   ./setup-in-kind.sh                    # Minimal setup (KEDA + SQS + Operator)
#   ./setup-in-kind.sh --full             # All components
#   ./setup-in-kind.sh --with-s3 --with-gateway  # S3 + Gateway only

set -euo pipefail

# Parse options
INSTALL_S3=false
INSTALL_GATEWAY=false
INSTALL_PROMETHEUS=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --full)
      INSTALL_S3=true
      INSTALL_GATEWAY=true
      INSTALL_PROMETHEUS=true
      shift
      ;;
    --with-s3)
      INSTALL_S3=true
      shift
      ;;
    --with-gateway)
      INSTALL_GATEWAY=true
      shift
      ;;
    --with-prometheus)
      INSTALL_PROMETHEUS=true
      shift
      ;;
    --help)
      grep '^#' "$0" | grep -v '#!/' | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "[!] Unknown option: $1"
      echo "    Run with --help for usage information"
      exit 1
      ;;
  esac
done

CLUSTER_NAME="${CLUSTER_NAME:-asya-local}"
SYSTEM_NAMESPACE="asya-system"
ACTOR_NAMESPACE="default"

echo "=== Asya🎭 Quick Setup for Kind ==="
echo "Cluster name: $CLUSTER_NAME"
echo "System namespace: $SYSTEM_NAMESPACE"
echo "Actor namespace: $ACTOR_NAMESPACE"
echo ""
echo "Components to install:"
echo "  - KEDA: yes"
echo "  - LocalStack (SQS): yes"
echo "  - Operator: yes"
echo "  - S3 Storage: $INSTALL_S3"
echo "  - Gateway: $INSTALL_GATEWAY"
echo "  - Prometheus: $INSTALL_PROMETHEUS"
echo ""

# Check prerequisites
echo "[.] Checking prerequisites..."
for cmd in kind kubectl helm docker; do
  if ! command -v "$cmd" > /dev/null 2>&1; then
    echo "[-] Error: $cmd is not installed"
    echo "    See docs/quickstart/README.md for installation instructions"
    exit 1
  fi
done
echo "[+] All prerequisites installed"
echo ""

# Create Kind cluster
if kind get clusters 2> /dev/null | grep -q "^${CLUSTER_NAME}$"; then
  echo "[!] Cluster '$CLUSTER_NAME' already exists, using existing cluster"
  kubectl config use-context "kind-${CLUSTER_NAME}"
else
  echo "[.] Creating Kind cluster..."
  cat > /tmp/kind-config-$$.yaml << EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 8080
    protocol: TCP
EOF

  kind create cluster --name "$CLUSTER_NAME" --config /tmp/kind-config-$$.yaml
  rm /tmp/kind-config-$$.yaml
  kubectl config use-context "kind-${CLUSTER_NAME}"
  echo "[+] Kind cluster created"
fi
echo ""

# Install KEDA
echo "[.] Installing KEDA..."
helm repo add kedacore https://kedacore.github.io/charts 2> /dev/null || true
helm repo update kedacore > /dev/null
if helm list -n keda-system 2> /dev/null | grep -q "^keda"; then
  echo "[!] KEDA already installed, skipping"
else
  helm install keda kedacore/keda --namespace keda-system --create-namespace
  echo "[+] KEDA installed"
fi
echo ""

# Install LocalStack
echo "[.] Installing LocalStack (SQS emulation)..."
helm repo add localstack https://helm.localstack.cloud 2> /dev/null || true
helm repo update localstack > /dev/null
if helm list -n "$SYSTEM_NAMESPACE" 2> /dev/null | grep -q "^localstack"; then
  echo "[!] LocalStack already installed, skipping"
else
  helm install localstack localstack/localstack \
    --namespace "$SYSTEM_NAMESPACE" \
    --create-namespace \
    --set image.tag=latest

  kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=localstack \
    -n "$SYSTEM_NAMESPACE" --timeout=300s
  echo "[+] LocalStack installed"
fi
echo ""

# Install Asya Operator
echo "[.] Installing Asya🎭 Operator..."

# Install CRD
echo "[.] Installing AsyncActor CRD..."
kubectl apply -f https://raw.githubusercontent.com/deliveryhero/asya/refs/heads/main/src/asya-operator/config/crd/asya.sh_asyncactors.yaml

# Create AWS credentials secret
if kubectl get secret sqs-secret -n "$SYSTEM_NAMESPACE" > /dev/null 2>&1; then
  echo "[!] SQS secret already exists, skipping"
else
  kubectl create secret generic sqs-secret \
    --namespace "$SYSTEM_NAMESPACE" \
    --from-literal=access-key-id=test \
    --from-literal=secret-access-key=test
fi

# Add Helm repository
helm repo add asya https://asya.sh/charts 2> /dev/null || true
helm repo update asya > /dev/null

# Create operator values
cat > /tmp/operator-values-$$.yaml << EOF
image:
  repository: ghcr.io/deliveryhero/asya-operator
transports:
  sqs:
    enabled: true
    config:
      region: us-east-1
      accountId: "000000000000"
      endpoint: http://localstack.${SYSTEM_NAMESPACE}.svc.cluster.local:4566
      credentials:
        accessKeyIdSecretRef:
          name: sqs-secret
          key: access-key-id
        secretAccessKeySecretRef:
          name: sqs-secret
          key: secret-access-key
EOF

if helm list -n "$SYSTEM_NAMESPACE" 2> /dev/null | grep -q "^asya-operator"; then
  echo "[!] Operator already installed, upgrading..."
  helm upgrade asya-operator asya/asya-operator \
    -n "$SYSTEM_NAMESPACE" \
    -f /tmp/operator-values-$$.yaml
else
  helm install asya-operator asya/asya-operator \
    -n "$SYSTEM_NAMESPACE" \
    --create-namespace \
    -f /tmp/operator-values-$$.yaml
fi

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=asya-operator \
  -n "$SYSTEM_NAMESPACE" --timeout=300s
echo "[+] Operator installed"
echo ""

# Deploy hello actor
echo "[.] Deploying hello actor..."

cat > /tmp/handler-$$.py << EOF
import time

def process(payload: dict) -> dict:
    time.sleep(1)
    return {
        **payload,
        "greeting": f"Hello, {payload.get('name', 'World')}!"
    }
EOF

cat > /tmp/Dockerfile-$$ << EOF
FROM python:3.13-slim
WORKDIR /app
COPY handler.py .
EOF

# Build and load image
cp /tmp/handler-$$.py handler.py
cp /tmp/Dockerfile-$$ Dockerfile
docker build -t my-hello-actor:latest -f Dockerfile . > /dev/null 2>&1
rm handler.py Dockerfile
kind load docker-image my-hello-actor:latest --name "$CLUSTER_NAME"

# Deploy actor
cat > /tmp/hello-actor-$$.yaml << EOF
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello
  namespace: ${ACTOR_NAMESPACE}
spec:
  transport: sqs
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
          image: my-hello-actor:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: "handler.process"
          - name: PYTHONPATH
            value: /app
          - name: AWS_ACCESS_KEY_ID
            value: "test"
          - name: AWS_SECRET_ACCESS_KEY
            value: "test"
          - name: AWS_REGION
            value: "us-east-1"
EOF

kubectl apply -f /tmp/hello-actor-$$.yaml
echo "[+] Hello actor deployed"
echo ""

# Clean up temp files
rm /tmp/operator-values-$$.yaml /tmp/handler-$$.py /tmp/Dockerfile-$$ /tmp/hello-actor-$$.yaml

# Install S3 storage (optional)
if [ "$INSTALL_S3" = true ]; then
  echo "[.] Installing S3 storage (crew actors)..."

  # Create S3 buckets
  kubectl run aws-cli-create-buckets --rm -i --restart=Never --image=amazon/aws-cli \
    --namespace "$SYSTEM_NAMESPACE" \
    --env="AWS_ACCESS_KEY_ID=test" \
    --env="AWS_SECRET_ACCESS_KEY=test" \
    --env="AWS_DEFAULT_REGION=us-east-1" \
    --command -- sh -c "
      aws --endpoint-url=http://localstack.${SYSTEM_NAMESPACE}.svc.cluster.local:4566 s3 mb s3://asya-results-bucket || true
      aws --endpoint-url=http://localstack.${SYSTEM_NAMESPACE}.svc.cluster.local:4566 s3 mb s3://asya-errors-bucket || true
    " > /dev/null 2>&1

  # Determine gateway URL based on whether gateway will be installed
  if [ "$INSTALL_GATEWAY" = true ]; then
    GATEWAY_URL="http://asya-gateway.${SYSTEM_NAMESPACE}.svc.cluster.local:8080"
  else
    GATEWAY_URL=""
  fi

  # Install crew actors
  cat > /tmp/crew-values-$$.yaml << EOF
happy-end:
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_GATEWAY_URL
            value: "${GATEWAY_URL}"
          - name: ASYA_S3_BUCKET
            value: "asya-results-bucket"
          - name: ASYA_S3_ENDPOINT
            value: "http://localstack.${SYSTEM_NAMESPACE}.svc.cluster.local:4566"
          - name: ASYA_S3_REGION
            value: "us-east-1"
          - name: AWS_ACCESS_KEY_ID
            value: "test"
          - name: AWS_SECRET_ACCESS_KEY
            value: "test"

error-end:
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_GATEWAY_URL
            value: "${GATEWAY_URL}"
          - name: ASYA_S3_BUCKET
            value: "asya-errors-bucket"
          - name: ASYA_S3_ENDPOINT
            value: "http://localstack.${SYSTEM_NAMESPACE}.svc.cluster.local:4566"
          - name: ASYA_S3_REGION
            value: "us-east-1"
          - name: AWS_ACCESS_KEY_ID
            value: "test"
          - name: AWS_SECRET_ACCESS_KEY
            value: "test"
EOF

  if helm list -n "$SYSTEM_NAMESPACE" 2> /dev/null | grep -q "^asya-crew"; then
    helm upgrade asya-crew asya/asya-crew \
      -n "$SYSTEM_NAMESPACE" \
      -f /tmp/crew-values-$$.yaml
  else
    helm install asya-crew asya/asya-crew \
      -n "$SYSTEM_NAMESPACE" \
      -f /tmp/crew-values-$$.yaml
  fi

  rm /tmp/crew-values-$$.yaml
  echo "[+] S3 storage installed"
  echo ""
fi

# Install Gateway (optional)
if [ "$INSTALL_GATEWAY" = true ]; then
  echo "[.] Installing Gateway with PostgreSQL..."

  # Install PostgreSQL
  if kubectl get deployment asya-gateway-postgresql -n "$SYSTEM_NAMESPACE" > /dev/null 2>&1; then
    echo "[!] PostgreSQL already installed, skipping"
  else
    kubectl apply -f - << EOF
apiVersion: v1
kind: Service
metadata:
  name: asya-gateway-postgresql
  namespace: ${SYSTEM_NAMESPACE}
spec:
  selector:
    app: postgresql
  ports:
    - port: 5432
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: asya-gateway-postgresql
  namespace: ${SYSTEM_NAMESPACE}
spec:
  selector:
    matchLabels:
      app: postgresql
  template:
    metadata:
      labels:
        app: postgresql
    spec:
      containers:
        - name: postgres
          image: 'postgres:15-alpine'
          env:
            - name: POSTGRES_USER
              value: asya
            - name: POSTGRES_PASSWORD
              value: asya
            - name: POSTGRES_DB
              value: asya
EOF
  fi

  # Create PostgreSQL secret
  if kubectl get secret asya-gateway-postgresql -n "$SYSTEM_NAMESPACE" > /dev/null 2>&1; then
    echo "[!] PostgreSQL secret already exists, skipping"
  else
    kubectl create secret generic asya-gateway-postgresql \
      --namespace "$SYSTEM_NAMESPACE" \
      --from-literal=password=asya
  fi

  # Install Gateway
  cat > /tmp/gateway-values-$$.yaml << EOF
image:
  repository: ghcr.io/deliveryhero/asya-gateway
  tag: latest

config:
  sqsEndpoint: http://localstack.${SYSTEM_NAMESPACE}.svc.cluster.local:4566
  sqsRegion: us-east-1
  database:
    host: asya-gateway-postgresql.${SYSTEM_NAMESPACE}.svc.cluster.local
    name: asya
    user: asya
    password: asya

routes:
  tools:
  - name: hello
    description: Greets users by name
    parameters:
      name:
        type: string
        required: true
        description: Name to greet
    route: [hello]

env:
- name: AWS_ACCESS_KEY_ID
  value: "test"
- name: AWS_SECRET_ACCESS_KEY
  value: "test"
EOF

  if helm list -n "$SYSTEM_NAMESPACE" 2> /dev/null | grep -q "^asya-gateway"; then
    helm upgrade asya-gateway asya/asya-gateway \
      -n "$SYSTEM_NAMESPACE" \
      -f /tmp/gateway-values-$$.yaml
  else
    helm install asya-gateway asya/asya-gateway \
      -n "$SYSTEM_NAMESPACE" \
      -f /tmp/gateway-values-$$.yaml
  fi

  kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=asya-gateway \
    -n "$SYSTEM_NAMESPACE" --timeout=300s

  rm /tmp/gateway-values-$$.yaml

  # Update operator for gateway integration
  cat > /tmp/operator-values-gateway-$$.yaml << EOF
image:
  repository: ghcr.io/deliveryhero/asya-operator
transports:
  sqs:
    enabled: true
    config:
      region: us-east-1
      accountId: "000000000000"
      endpoint: http://localstack.${SYSTEM_NAMESPACE}.svc.cluster.local:4566
      credentials:
        accessKeyIdSecretRef:
          name: sqs-secret
          key: access-key-id
        secretAccessKeySecretRef:
          name: sqs-secret
          key: secret-access-key
gatewayURL: "http://asya-gateway.${SYSTEM_NAMESPACE}.svc.cluster.local:8080"
EOF

  helm upgrade asya-operator asya/asya-operator \
    -n "$SYSTEM_NAMESPACE" \
    -f /tmp/operator-values-gateway-$$.yaml

  rm /tmp/operator-values-gateway-$$.yaml

  # Update crew if it was installed
  if [ "$INSTALL_S3" = true ]; then
    echo "[.] Updating crew for gateway reporting..."
    cat > /tmp/crew-values-gateway-$$.yaml << EOF
happy-end:
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_GATEWAY_URL
            value: "http://asya-gateway.${SYSTEM_NAMESPACE}.svc.cluster.local:8080"
          - name: ASYA_S3_BUCKET
            value: "asya-results-bucket"
          - name: ASYA_S3_ENDPOINT
            value: "http://localstack.${SYSTEM_NAMESPACE}.svc.cluster.local:4566"
          - name: ASYA_S3_REGION
            value: "us-east-1"
          - name: AWS_ACCESS_KEY_ID
            value: "test"
          - name: AWS_SECRET_ACCESS_KEY
            value: "test"

error-end:
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_GATEWAY_URL
            value: "http://asya-gateway.${SYSTEM_NAMESPACE}.svc.cluster.local:8080"
          - name: ASYA_S3_BUCKET
            value: "asya-errors-bucket"
          - name: ASYA_S3_ENDPOINT
            value: "http://localstack.${SYSTEM_NAMESPACE}.svc.cluster.local:4566"
          - name: ASYA_S3_REGION
            value: "us-east-1"
          - name: AWS_ACCESS_KEY_ID
            value: "test"
          - name: AWS_SECRET_ACCESS_KEY
            value: "test"
EOF

    helm upgrade asya-crew asya/asya-crew \
      -n "$SYSTEM_NAMESPACE" \
      -f /tmp/crew-values-gateway-$$.yaml

    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=asya-crew \
      -n "$SYSTEM_NAMESPACE" --timeout=300s

    rm /tmp/crew-values-gateway-$$.yaml
  fi

  echo "[+] Gateway installed"
  echo ""
fi

# Install Prometheus (optional)
if [ "$INSTALL_PROMETHEUS" = true ]; then
  echo "[.] Installing Prometheus with Grafana..."
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2> /dev/null || true
  helm repo update prometheus-community > /dev/null

  if helm list -n monitoring 2> /dev/null | grep -q "^prometheus"; then
    echo "[!] Prometheus already installed, skipping"
  else
    helm install prometheus prometheus-community/kube-prometheus-stack \
      --namespace monitoring \
      --create-namespace
  fi

  # Configure ServiceMonitors
  kubectl apply -f - << EOF
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: asya-operator
  namespace: ${SYSTEM_NAMESPACE}
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: asya-operator
  endpoints:
  - port: metrics
    interval: 30s
EOF

  echo "[+] Prometheus installed"
  echo ""
fi

# Print success message and next steps
echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Cluster: $CLUSTER_NAME"
echo "Context: kind-${CLUSTER_NAME}"
echo ""
echo "Next steps:"
echo ""

if [ "$INSTALL_GATEWAY" = true ]; then
  echo "1. Install asya CLI:"
  echo "   pip install git+https://github.com/deliveryhero/asya.git#subdirectory=src/asya-cli"
  echo ""
  echo "2. Port-forward gateway (in a separate terminal):"
  echo "   kubectl port-forward -n ${SYSTEM_NAMESPACE} svc/asya-gateway 8080:80"
  echo ""
  echo "3. Test the hello actor:"
  echo "   export ASYA_CLI_MCP_URL=http://localhost:8080/"
  echo "   asya mcp list"
  echo "   asya mcp call hello --name=Asya"
  echo "   asya mcp call hello --name=Asya --stream"
else
  echo "1. Send a test message to the hello actor:"
  echo "   MSG='{\"id\":\"test-123\",\"route\":{\"actors\":[\"hello\"],\"current\":0},\"payload\":{\"name\":\"Asya\"}}'"
  echo "   kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \\"
  echo "     --namespace ${ACTOR_NAMESPACE} \\"
  echo "     --env=\"AWS_ACCESS_KEY_ID=test\" \\"
  echo "     --env=\"AWS_SECRET_ACCESS_KEY=test\" \\"
  echo "     --env=\"AWS_DEFAULT_REGION=us-east-1\" \\"
  echo "     --command -- sh -c \\"
  echo "       \"aws sqs send-message \\"
  echo "         --endpoint-url=http://localstack.${SYSTEM_NAMESPACE}.svc.cluster.local:4566 \\"
  echo "         --queue-url http://localstack.${SYSTEM_NAMESPACE}.svc.cluster.local:4566/000000000000/asya-${ACTOR_NAMESPACE}-hello \\"
  echo "         --message-body '\$MSG'\""
  echo ""
  echo "2. Watch the actor scale and process:"
  echo "   kubectl get pods -l asya.sh/actor=hello -w"
fi

echo ""
echo "3. Check actor logs:"
echo "   kubectl logs -l asya.sh/actor=hello -c asya-runtime"
echo ""

if [ "$INSTALL_PROMETHEUS" = true ]; then
  echo "4. Access Grafana (in a separate terminal):"
  echo "   kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80"
  echo "   Credentials: admin / prom-operator"
  echo ""
fi

echo "For more examples, see: docs/quickstart/README.md"
echo ""
