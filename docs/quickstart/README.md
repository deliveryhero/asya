<!--
IMPORTANT: This file is tested as part of e2e test suite: /testing/e2e/tests/test_quickstart_readme.py
- All ```bash commands are executed during testing
- All typed code blocks (```python, ```yaml, ```dockerfile, etc.) with first line as "# filename" are written to files
-->
# Getting Started with Asya🎭 Locally

**Core idea**: Build multi-step AI/ML pipelines where each step deployed as an [actor](https://en.wikipedia.org/wiki/Actor_model) and scales independently. No infrastructure code in your code - just pure Python.

## What You'll Learn

- Create a Kind cluster to run Kubernetes locally in Docker, and install KEDA for autoscaling
- Deploy the Asya operator with SQS transport (running via LocalStack)
- Build and deploy your first actor with scale-to-zero capability
- Test autoscaling by sending messages to actor queues
- Optionally add S3 storage, MCP gateway, and Prometheus monitoring

## Prerequisites

Before you begin, install:

- [Docker](https://www.docker.com/get-started/) 24+
- [kubectl](https://kubernetes.io/docs/tasks/tools/) 1.28+
- [Helm](https://helm.sh/docs/intro/install/) 3.12+
- [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) 0.20+

## Setup Options

Choose your setup based on your needs:

- **[Minimal Setup](#minimal-setup)** - KEDA + SQS + Asya Operator (core functionality only)
- **[+ S3 Storage](#add-s3-storage-optional)** - Add persistence of the result message
- **[+ Asya Gateway](#add-gateway-optional)** - Add MCP HTTP API with PostgreSQL
- **[+ Prometheus](#add-prometheus-optional)** - Add observability

## Initial Setup

### 1. Create Kind Cluster

Create Kind configuration file:
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

Create Kind cluster:
```bash
kind create cluster --name asya-local --config kind-config.yaml
kubectl config use-context kind-asya-local
```

## Minimal Setup

**What you get**: Core actor framework with SQS transport and autoscaling

### 1. Install KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda \
  --namespace keda-system \
  --create-namespace \
  --timeout=3m
```

### 2. Install LocalStack (SQS)

LocalStack provides local AWS SQS emulation:

```bash
helm repo add localstack https://helm.localstack.cloud
helm install localstack localstack/localstack \
  --namespace asya-system \
  --create-namespace \
  --set image.tag=latest \
  --timeout=3m

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=localstack \
  -n asya-system --timeout=120s || true

kubectl get pods -l app.kubernetes.io/name=localstack -n asya-system
```

### 3. Install Asya🎭 Operator

Install `AsyncActor` CRD:

```bash
kubectl apply -f https://github.com/deliveryhero/asya/releases/latest/download/asya-crds.yaml
```

Add Helm repository:

```bash
helm repo add asya https://asya.sh/charts
#helm repo update  # to re-download repos
```

Create AWS credentials secret:

```bash
kubectl create secret generic sqs-secret \
  --namespace asya-system \
  --from-literal=access-key-id=test \
  --from-literal=secret-access-key=test
```

Install operator:

```yaml
# operator-values.yaml
transports:
  sqs:
    enabled: true
    config:
      region: us-east-1
      accountId: "000000000000"
      endpoint: http://localstack.asya-system.svc.cluster.local:4566
      credentials:
        accessKeyIdSecretRef:
          name: sqs-secret
          key: access-key-id
        secretAccessKeySecretRef:
          name: sqs-secret
          key: secret-access-key
```

```bash
helm install asya-operator asya/asya-operator \
  -n asya-system \
  --create-namespace \
  -f operator-values.yaml \
  --timeout=3m

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=asya-operator \
  -n asya-system --timeout=120s || true

kubectl get pods -l app.kubernetes.io/name=asya-operator -n asya-system
# NAME                             READY   STATUS    RESTARTS   AGE
# asya-operator-7c8cdc4ff4-4qj2f   1/1     Running   0          40s
```

In order to debug 🎭 behavior (e.g. if scaling doesn't work), it's good to check operator logs:
```bash
kubectl -n asya-system logs -l app.kubernetes.io/name=asya-operator
```

### 4. Deploy Your First Actor

Write a handler:

```python
# handler.py
import time

def process(payload: dict) -> dict:
    time.sleep(1)  # simulate workload
    return {
        **payload,
        "greeting": f"Hello, {payload.get('name', 'World')}!"
    }
```

Build a docker image and load it to kind context (in real world, use CI to build and push packages automatically):

```dockerfile
# Dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY handler.py .
```

```bash
docker build -t my-hello-actor:latest .
kind load docker-image my-hello-actor:latest --name asya-local
```

Deploy the actor:

```yaml
# hello-actor.yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello
  namespace: default
spec:
  transport: sqs
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    queueLength: 5  # for each 5 messages in queue create 1 new pod
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
```

```bash
kubectl apply -f hello-actor.yaml
sleep 1

kubectl get asya
# NAME    STATUS    RUNNING   FAILING   TOTAL   DESIRED   MIN   MAX   LAST-SCALE   AGE
# hello   Napping   0         0         0       0         0     10    -            18s
```
<!-- # kubectl get deployment -l asya.sh/asya=hello -->

The actor is in `Napping` state with 0 replicas, demonstrating scale-to-zero capability. It will automatically scale up when messages arrive in the queue.
See more on actor states [here](/docs/architecture/asya-operator.md#status-values).

### 5. Test the Actor

Send a message to the actor's SQS queue:

```bash
MSG='{"id":"test-123","route":{"actors":["hello"],"current":0},"payload":{"name":"Asya"}}'

kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace default \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      --queue-url http://localstack.asya-system.svc.cluster.local:4566/000000000000/asya-default-hello \
      --message-body '$MSG'
  "
```

Watch the actor scale up and process the message (timeout after 60s):


Read the logs using `kubectl logs` and find the greeting message (with timeout):

```bash
timeout 30s sh -c '
  until kubectl logs -l asya.sh/asya=hello -c asya-runtime | tee /dev/stderr | grep -q "greeting"; do
    sleep 1
  done
' && echo "[+] Found expected greeting in logs"
```

Expected output should contain:
```py
user_func returned: {'name': 'Asya', 'greeting': 'Hello, Asya!'}
```

Watch horizontal autoscaling by sending 25 messages to trigger multiple pods:

```bash
MSG='{"id":"test-123","route":{"actors":["hello"],"current":0},"payload":{"name":"Asya"}}'

kubectl run send-many-messages --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace default \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    for i in {1..25}; do
      aws sqs send-message \
        --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
        --queue-url http://localstack.asya-system.svc.cluster.local:4566/000000000000/asya-default-hello \
        --message-body '$MSG' &
    done
    wait
    echo '[+] All 25 messages sent'
  "
```

Watch the actor scale up to 5 pods (25 messages / 5 messages per pod):

```bash
timeout 60s kubectl get asya hello -w || true
```


## Add S3 Storage (Optional)

**What you get**: Pipeline completion with result persistence to S3

### 1. Create S3 Buckets

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-system \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- /bin/bash -c "
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 s3 mb s3://asya-results
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 s3 mb s3://asya-errors
  "
```

### 2. Install Crew Actors

Crew actors are pre-defined system actors proved by the framework to handle typical operations like message persistence (`happy-end` and `error-end`):

```yaml
# crew-values.yaml
happy-end:
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_GATEWAY_URL
            value: ""  # Set this when gateway is installed
          - name: ASYA_S3_BUCKET
            value: "asya-results"
          - name: ASYA_S3_ENDPOINT
            value: "http://localstack.asya-system.svc.cluster.local:4566"
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
            value: ""  # Set this when gateway is installed
          - name: ASYA_S3_BUCKET
            value: "asya-errors"
          - name: ASYA_S3_ENDPOINT
            value: "http://localstack.asya-system.svc.cluster.local:4566"
          - name: ASYA_S3_REGION
            value: "us-east-1"
          - name: AWS_ACCESS_KEY_ID
            value: "test"
          - name: AWS_SECRET_ACCESS_KEY
            value: "test"
```

```bash
helm install asya-crew asya/asya-crew \
  -n asya-system \
  -f crew-values.yaml \
  --timeout=3m
```

Your pipeline results are now automatically persisted to S3: whenever an actor finishes processing the last message in the route, 🎭 automatically sends it to `happy-end` actor to persist it on S3. Similarly, error messages will be sent to `error-end`.

### 3. Verify S3 Persistence

Send a test message and verify it's persisted to S3:

```bash
# Send a message through hello actor
MSG='{"id":"s3-test-001","route":{"actors":["hello"],"current":0},"payload":{"name":"S3 Test"}}'

kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace default \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      --queue-url http://localstack.asya-system.svc.cluster.local:4566/000000000000/asya-default-hello \
      --message-body '$MSG'
  "
```

Wait for processing and check S3 for the result:

```bash
# Wait a few seconds for message to be processed and persisted
sleep 10

# List objects in results bucket
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-system \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- /bin/bash -c "
    echo '[+] Listing S3 objects in asya-results bucket:'
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      s3 ls s3://asya-results/ --recursive
  "
```

You should see an S3 object with a key like `s3-test-001.json`. Download and inspect it:

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-system \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- /bin/bash -c "
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      s3 cp s3://asya-results/s3-test-001.json - | cat
  "
```

Expected output should contain the greeting:
```json
{
  "id": "s3-test-001",
  "route": {"actors": ["hello"], "current": 1},
  "payload": {
    "name": "S3 Test",
    "greeting": "Hello, S3 Test!"
  }
}
```


## Add Gateway (Optional)

**What you get**: HTTP API, MCP tools, SSE streaming, envelope tracking

### 1. Install PostgreSQL

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: asya-gateway-postgresql
  namespace: asya-system
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
  namespace: asya-system
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
```

### 2. Create PostgreSQL Secret

```bash
kubectl create secret generic asya-gateway-postgresql \
  --namespace asya-system \
  --from-literal=password=asya
```

---

### 3. Install Gateway

```yaml
# gateway-values.yaml
image:
  repository: ghcr.io/deliveryhero/asya-gateway
  tag: latest

config:
  sqsEndpoint: http://localstack.asya-system.svc.cluster.local:4566
  sqsRegion: us-east-1
  database:
    host: asya-gateway-postgresql.asya-system.svc.cluster.local
    name: asya
    user: asya
    password: asya

env:
- name: AWS_ACCESS_KEY_ID
  value: "test"
- name: AWS_SECRET_ACCESS_KEY
  value: "test"
```

```bash
helm install asya-gateway asya/asya-gateway \
  -n asya-system \
  -f gateway-values.yaml \
  --timeout=3m

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=asya-gateway \
  -n asya-system --timeout=120s || true

kubectl get pods -l app.kubernetes.io/name=asya-gateway -n asya-system
```

### 4. Update Operator for Gateway Integration

Update the operator configuration to include the gateway URL:

```bash
helm upgrade asya-operator asya/asya-operator \
  -n asya-system \
  -f operator-values.yaml \
  --set gatewayURL="http://asya-gateway.asya-system.svc.cluster.local:8080" \
  --timeout=3m
```

### 5. Update Crew Actors for Gateway Reporting

Update crew configuration to report status to the gateway:

```bash
helm upgrade asya-crew asya/asya-crew \
  -n asya-system \
  -f crew-values.yaml \
  --set-string 'happy-end.workload.template.spec.containers[0].env[0].value=http://asya-gateway.asya-system.svc.cluster.local:8080' \
  --set-string 'error-end.workload.template.spec.containers[0].env[0].value=http://asya-gateway.asya-system.svc.cluster.local:8080' \
  --timeout=3m
```

Wait for crew actors to be ready:

```bash
kubectl wait --for=condition=ready pod -l asya.sh/asya=happy-end \
  -n asya-system --timeout=120s || true

kubectl wait --for=condition=ready pod -l asya.sh/asya=error-end \
  -n asya-system --timeout=120s || true
```

Verify S3 persistence with gateway reporting:

```bash
# Send a test message
MSG='{"id":"gateway-test-001","route":{"actors":["hello"],"current":0},"payload":{"name":"Gateway Test"}}'

kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace default \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      --queue-url http://localstack.asya-system.svc.cluster.local:4566/000000000000/asya-default-hello \
      --message-body '$MSG'
  "
```

Check that result is persisted to S3:

```bash
# Wait for processing
sleep 10

# Verify S3 object exists
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-system \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- /bin/bash -c "
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      s3 cp s3://asya-results/gateway-test-001.json - | cat
  "
```

### 6. Use the Gateway

Install CLI:

```bash
pip install git+https://github.com/deliveryhero/asya.git#subdirectory=src/asya-cli
```

Port-forward and test:

```bash
kubectl port-forward -n asya-system svc/asya-gateway 8080:80 &
PORT_FORWARD_PID=$!
sleep 2  # Wait for port-forward to establish

export ASYA_CLI_MCP_URL=http://localhost:8080/

# List tools
asya mcp list

# Call an actor
asya mcp call hello --name=Asya

# Stream progress
asya mcp call hello --name=Asya --stream

kill $PORT_FORWARD_PID 2>/dev/null || true
```

## Add Prometheus (Optional)

**What you get**: Metrics collection and observability

### 1. Install Prometheus

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --timeout=5m
```

### 2. Configure ServiceMonitors

The Asya operator exposes metrics at `:8080/metrics`. Create a ServiceMonitor:

```bash
kubectl apply -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: asya-operator
  namespace: asya-system
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: asya-operator
  endpoints:
  - port: metrics
    interval: 30s
EOF
```

### 3. Access Grafana

```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80 &
GRAFANA_PID=$!
sleep 2  # Wait for port-forward to establish

# Now access http://localhost:3000 in your browser
# When done:
kill $GRAFANA_PID 2>/dev/null || true
```

Default credentials: `admin` / `prom-operator`

Import Asya dashboards from the [monitoring guide](../operate/monitoring.md).

## Testing Your Setup

Send a message and watch scaling:

```bash
# Send message via MCP gateway
asya mcp call hello --name="Test"

# Watch pods scale (timeout after 60s)
timeout 60s kubectl get pods -l asya.sh/asya=hello -w || true

# Check logs
POD=$(kubectl get pods -l asya.sh/asya=hello -o name | head -1)
kubectl logs $POD -c asya-runtime
kubectl logs $POD -c asya-sidecar
```

Verify end-to-end flow with S3 persistence:

```bash
# Check envelope status via gateway
asya mcp status <envelope-id>

# List all objects in S3 results bucket
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-system \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- /bin/bash -c "
    echo '[+] All results persisted to S3:'
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      s3 ls s3://asya-results/ --recursive
  "
```

## Alternative: Quick E2E Setup

For rapid testing with all components:

```bash
cd testing/e2e
make up PROFILE=sqs-s3
```

This deploys everything in one command but uses test configurations.

## Production Deployment

For production on AWS, replace LocalStack with real AWS services:

```yaml
# operator-values.yaml for production
transports:
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
      accountId: "123456789012"
      # Remove endpoint for production AWS
      actorRoleArn: "arn:aws:iam::123456789012:role/asya-actor-role"
      queues:
        autoCreate: true
        dlq:
          enabled: true
          maxRetryCount: 3
      # Use IRSA instead of static credentials
```

See [AWS EKS Installation](../install/aws-eks.md) for full production guide.

## What's Next?

### For Data Scientists

- **[Quickstart for Data Scientists](for-data-scientists.md)** - Class handlers, model loading, dynamic routing
- **[Flow DSL](../architecture/asya-flow.md)** - Write pipelines in Python-like syntax

**Use cases**:
- Multi-step LLM workflows (RAG → generate → judge → refine)
- Document processing (OCR → classify → extract → store)
- Image pipelines (resize → detect → classify → tag)

### For Platform Engineers

- **[Quickstart for Platform Engineers](for-platform-engineers.md)** - Deployment strategies, scaling policies
- **[AWS EKS Installation](../install/aws-eks.md)** - Production deployment
- **[Monitoring](../operate/monitoring.md)** - Metrics, alerts, dashboards
- **[Troubleshooting](../operate/troubleshooting.md)** - Common issues

## Learn More

- [Core Concepts](../concepts.md) - Actors, envelopes, sidecars, routing
- [Motivation](../motivation.md) - Why Asya🎭 exists, when to use it
- [Architecture](../architecture/README.md) - Deep dive into system design
- [Examples](https://github.com/deliveryhero/asya/tree/main/examples) - Sample actors and flows

## Clean Up

### Clean Up Specific Components

If you want to remove specific components while keeping the cluster:

```bash
# Remove Prometheus (if installed)
helm uninstall prometheus -n monitoring
kubectl delete namespace monitoring

# Remove Gateway (if installed)
helm uninstall asya-gateway -n asya-system
kubectl delete secret asya-gateway-postgresql -n asya-system
kubectl delete deployment asya-gateway-postgresql -n asya-system
kubectl delete service asya-gateway-postgresql -n asya-system

# Remove Crew actors (if installed)
helm uninstall asya-crew -n asya-system

# Remove your custom actors
kubectl delete asya hello -n default

# Remove Asya operator
helm uninstall asya-operator -n asya-system

# Remove LocalStack
helm uninstall localstack -n asya-system

# Remove KEDA
helm uninstall keda -n keda-system
kubectl delete namespace keda-system

# Remove CRDs
kubectl delete crd asyncactors.asya.sh

# Remove namespace
kubectl delete namespace asya-system
```

### Clean Up Everything

To completely remove the Kind cluster and all components:

```bash
kind delete cluster --name asya-local
```

---

**Next**: Choose your path - [Data Scientists](for-data-scientists.md) or [Platform Engineers](for-platform-engineers.md)
