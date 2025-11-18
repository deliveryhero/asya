# Local Kind Installation

Local development cluster with Kind (Kubernetes in Docker).

## Prerequisites

- [Docker](https://www.docker.com/get-started/)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [Helm 3.0+](https://helm.sh/docs/intro/install/)
- [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation)

## Quick Start

Use E2E test infrastructure for fastest setup:

```bash
cd testing/e2e

# Deploy full stack (RabbitMQ + MinIO)
make up PROFILE=rabbitmq-minio

# Or deploy AWS stack (LocalStack SQS + MinIO)
make up PROFILE=sqs-minio
```

**Includes**:

- Kind cluster
- KEDA operator
- RabbitMQ or LocalStack SQS
- MinIO (S3-compatible storage)
- PostgreSQL (for gateway)
- Asya operator, gateway, crew actors
- Prometheus, Grafana (monitoring)

**See**: `testing/e2e/README.md` for details.

## Manual Installation

### 1. Create Kind Cluster

```yaml
# kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:

- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 8080
    protocol: TCP
```

```bash
kind create cluster --name asya-local --config kind-config.yaml
```

### 2. Install KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda --namespace keda --create-namespace
```

### 3. Install RabbitMQ

```bash
kubectl apply -f testing/e2e/manifests/rabbitmq.yaml
```

Wait for ready:
```bash
kubectl wait --for=condition=ready pod -l app=rabbitmq --timeout=300s
```

### 4. Install MinIO

```bash
kubectl apply -f testing/e2e/manifests/minio.yaml
```

Create bucket:
```bash
kubectl exec -it deploy/minio -- mc alias set local http://localhost:9000 minioadmin minioadmin
kubectl exec -it deploy/minio -- mc mb local/asya-results
```

### 5. Install PostgreSQL

```bash
kubectl apply -f testing/e2e/manifests/postgres.yaml
```

### 6. Install Asya Operator

```bash
# Install CRDs
kubectl apply -f src/asya-operator/config/crd/

# Create operator values
cat > operator-values.yaml <<EOF
transports:
  rabbitmq:
    enabled: true
    type: rabbitmq
    config:
      host: rabbitmq.default.svc.cluster.local
      port: 5672
      username: guest
      password: guest
EOF

# Install operator
helm install asya-operator deploy/helm-charts/asya-operator/ \
  -n asya-system --create-namespace \
  -f operator-values.yaml
```

### 7. Install Gateway

```bash
cat > gateway-values.yaml <<EOF
config:
  postgresHost: postgres.default.svc.cluster.local
  postgresDatabase: asya_gateway
  postgresUsername: postgres
  postgresPassword: postgres

routes:
  tools:
  - name: hello
    description: Hello actor
    parameters:
      who:
        type: string
        required: true
    route: [hello-actor]
EOF

helm install asya-gateway deploy/helm-charts/asya-gateway/ \
  -f gateway-values.yaml
```

### 8. Install Crew

```bash
cat > crew-values.yaml <<EOF
happy-end:
  enabled: true
  transport: rabbitmq
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: handlers.end_handlers.happy_end_handler
          - name: ASYA_S3_BUCKET
            value: asya-results
          - name: ASYA_S3_ENDPOINT
            value: http://minio.default.svc.cluster.local:9000
          - name: ASYA_S3_ACCESS_KEY
            value: minioadmin
          - name: ASYA_S3_SECRET_KEY
            value: minioadmin

error-end:
  enabled: true
  transport: rabbitmq
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: handlers.end_handlers.error_end_handler
          - name: ASYA_S3_BUCKET
            value: asya-results
          - name: ASYA_S3_ENDPOINT
            value: http://minio.default.svc.cluster.local:9000
          - name: ASYA_S3_ACCESS_KEY
            value: minioadmin
          - name: ASYA_S3_SECRET_KEY
            value: minioadmin
EOF

helm install asya-crew deploy/helm-charts/asya-crew/ \
  --namespace default \
  -f crew-values.yaml
```

### 9. Deploy Test Actor

```yaml
# hello-actor.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: hello-handler
data:
  handler.py: |
    def process(payload: dict) -> dict:
        return {"message": f"Hello {payload.get('who', 'World')}!"}
---
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello-actor
spec:
  transport: rabbitmq
  scaling:
    minReplicas: 0
    maxReplicas: 5
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
          env:
          - name: ASYA_HANDLER
            value: "handler.process"
          - name: PYTHONPATH
            value: "/app"
          volumeMounts:
          - name: handler
            mountPath: /app/handler.py
            subPath: handler.py
        volumes:
        - name: handler
          configMap:
            name: hello-handler
```

```bash
kubectl apply -f hello-actor.yaml
```

## Testing

### Via asya-mcp Tool

```bash
# Install asya-cli
uv pip install -e ./src/asya-cli

# Port-forward gateway
kubectl port-forward svc/asya-gateway 8089:80

# Set gateway URL
export ASYA_CLI_MCP_URL=http://localhost:8089/

# List tools
asya-mcp list

# Call tool
asya-mcp call hello --who=World
```

### Via RabbitMQ Direct

```bash
# Port-forward RabbitMQ
kubectl port-forward svc/rabbitmq 15672:15672 5672:5672

# Open management UI: http://localhost:15672 (guest/guest)

# Send message via Python
python3 <<EOF
import pika
import json

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

envelope = {
    "id": "test-1",
    "route": {"actors": ["hello-actor"], "current": 0},
    "payload": {"who": "Local"}
}

channel.basic_publish(
    exchange='',
    routing_key='asya-hello-actor',
    body=json.dumps(envelope)
)
connection.close()
EOF
```

## Cleanup

```bash
# Delete cluster
kind delete cluster --name asya-local

# Or use E2E cleanup
cd testing/e2e
make down PROFILE=rabbitmq-minio
```

## Troubleshooting

**Pods not starting**:
```bash
kubectl describe pod <pod-name>
kubectl logs <pod-name>
```

**RabbitMQ connection errors**:
```bash
kubectl logs -l asya.sh/actor=hello-actor -c asya-sidecar
```

**Queue not created**:
```bash
kubectl logs -n asya-system deploy/asya-operator
```
