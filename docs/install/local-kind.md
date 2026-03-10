# Local Kind Installation

Local development cluster with Kind (Kubernetes in Docker).

## Prerequisites

- [Docker](https://www.docker.com/get-started/)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [Helm 3.0+](https://helm.sh/docs/intro/install/)
- [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation)

## Quick Start

Use the E2E test infrastructure for the fastest setup:

```bash
cd testing/e2e

# Deploy RabbitMQ + MinIO stack
make up PROFILE=rabbitmq-minio

# Or deploy AWS-style stack (LocalStack SQS + S3)
make up PROFILE=sqs-s3
```

**Includes**:

- Kind cluster
- KEDA operator
- Crossplane with AWS provider
- RabbitMQ or LocalStack SQS
- MinIO or LocalStack S3
- PostgreSQL (for gateway)
- Asya gateway, crew actors, and test actors

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
helm upgrade --install asya-rabbitmq testing/e2e/charts/rabbitmq \
  --namespace asya-e2e --create-namespace

kubectl wait --for=condition=ready pod -l app=rabbitmq \
  -n asya-e2e --timeout=300s
```

### 4. Install MinIO

```bash
helm upgrade --install minio testing/e2e/charts/minio \
  --namespace asya-e2e --create-namespace
```

The chart automatically creates the `asya-results` and `asya-errors` buckets via a post-install job, so no manual `mc` calls are required.

### 5. Install PostgreSQL

```bash
helm upgrade --install asya-gateway-postgresql testing/e2e/charts/postgres \
  --namespace asya-e2e --create-namespace

kubectl wait --for=condition=ready pod -l app=postgresql \
  -n asya-e2e --timeout=300s
```

### 6. Install Crossplane and Asya Components

```bash
# Install Crossplane
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace

# Install Asya Crossplane chart
helm install asya-crossplane deploy/helm-charts/asya-crossplane/ \
  -n crossplane-system
```

### 7. Install Gateway

```bash
cat > gateway-values.yaml <<'EOF'
config:
  postgresHost: asya-gateway-postgresql.asya-e2e.svc.cluster.local
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
  -n asya-e2e --create-namespace \
  -f gateway-values.yaml
```

### 8. Install Crew

```bash
cat > crew-values.yaml <<'EOF'
x-sink:
  enabled: true
  transport: rabbitmq
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: asya_crew.checkpointer.handler
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints

x-sump:
  enabled: true
  transport: rabbitmq
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: asya_crew.checkpointer.handler
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints
EOF

helm install asya-crew deploy/helm-charts/asya-crew/ \
  --namespace asya-e2e \
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
    minReplicaCount: 0
    maxReplicaCount: 5
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

### Via asya mcp Tool

```bash
# Install asya-lab
uv pip install -e ./src/asya-lab

# Port-forward gateway
kubectl port-forward -n asya-e2e svc/asya-gateway 8089:80

# Set gateway URL
export ASYA_CLI_MCP_URL=http://localhost:8089/

# List tools
asya mcp list

# Call tool
asya mcp call hello --who=World
```

### Via RabbitMQ Direct

```bash
# Port-forward RabbitMQ
kubectl port-forward -n asya-e2e svc/asya-rabbitmq 15672:15672 5672:5672

# Open management UI: http://localhost:15672 (guest/guest)

# Send message via Python
python3 <<EOF
import pika
import json

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

message = {
    "id": "test-1",
    "route": {"prev": [], "curr": "hello-actor", "next": []},
    "payload": {"who": "Local"}
}

channel.basic_publish(
    exchange='',
    routing_key='asya-hello-actor',
    body=json.dumps(message)
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
kubectl describe asyncactor <actor-name>
kubectl get sqsqueue <queue-name> -o yaml
```
