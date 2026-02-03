<!--
IMPORTANT: All ```bash commands in this file are tested as part of e2e test suite: /testing/e2e/tests/test_quickstart_readme.py
-->
# Getting Started with Asya🎭 Locally

**Core idea**: Build multi-step AI/ML pipelines where each step deployed as an [actor](https://en.wikipedia.org/wiki/Actor_model) and scales independently. No infrastructure code in your code - just pure Python.

## What You'll Learn

- Create a Kind cluster to run Kubernetes locally in Docker, and install KEDA for autoscaling
- Deploy the Asya operator with SQS transport (running via LocalStack)
- Build and deploy your first actor with scale-to-zero capability
- Test autoscaling by sending messages to actor queues
- Optionally add S3 storage, MCP gateway, Prometheus monitoring, and Grafana dashboards

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
- **[+ Prometheus](#add-prometheus-optional)** - Add metrics collection and Grafana dashboards

## Initial Setup

### 1. Create Kind Cluster

```bash
cat > kind-config.yaml <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 8080
    protocol: TCP
EOF

kind create cluster --name asya-local --config kind-config.yaml
kubectl config use-context kind-asya-local
```

## Minimal Setup

**What you get**: Core actor framework with SQS transport and autoscaling

### 1. Install KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda --namespace keda-system --create-namespace
```

### 2. Install LocalStack (SQS)

LocalStack provides local AWS SQS emulation:

```bash
helm repo add localstack https://helm.localstack.cloud
helm install localstack localstack/localstack \
  --namespace asya-system \
  --create-namespace \
  --set image.tag=latest

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=localstack \
  -n asya-system --timeout=300s
```

### 3. Install Asya🎭 Operator

Install `AsyncActor` CRD:

<!-- TODO: fix CRD release instead:
kubectl apply -f https://github.com/deliveryhero/asya/releases/latest/download/asya-crds.yaml
-->
```bash
kubectl apply -f https://raw.githubusercontent.com/deliveryhero/asya/refs/heads/main/src/asya-operator/config/crd/asya.sh_asyncactors.yaml
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

```bash
# TODO: remove image.repository overload for 0.4.0+
cat > operator-values.yaml <<EOF
image:
  repository: ghcr.io/deliveryhero/asya-operator
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
EOF

helm install asya-operator asya/asya-operator \
  -n asya-system \
  --create-namespace \
  -f operator-values.yaml

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=asya-operator \
  -n asya-system --timeout=300s

# check manually:
kubectl -n asya-system get po -l app.kubernetes.io/name=asya-operator
# NAME                             READY   STATUS    RESTARTS   AGE
# asya-operator-7c8cdc4ff4-4qj2f   1/1     Running   0          40s
```

In order to debug 🎭 behavior (e.g. if scaling doesn't work), it's good to check operator logs:
```bash
kubectl -n asya-system logs -l app.kubernetes.io/name=asya-operator
```

### 4. Deploy Your First Actor

Write a handler:

```bash
cat > handler.py <<EOF
import time

def process(payload: dict) -> dict:
    time.sleep(1)  # simulate workload
    return {
        **payload,
        "greeting": f"Hello, {payload.get('name', 'World')}!"
    }
EOF
```

Build a docker image and load it to kind context (in real world, use CI to build and push packages automatically):

```bash
cat > Dockerfile <<EOF
FROM python:3.13-slim
WORKDIR /app
COPY handler.py .
EOF

docker build -t my-hello-actor:latest .
kind load docker-image my-hello-actor:latest --name asya-local
```

Deploy the actor:

```bash
cat > hello-actor.yaml <<EOF
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
EOF

kubectl apply -f hello-actor.yaml

kubectl get asya -l asya.sh/asya=hello
# NAME    STATUS    RUNNING   FAILING   TOTAL   DESIRED   MIN   MAX   LAST-SCALE   AGE
# hello   Napping   0         0         0       0         0     10    -            18s
```
<!-- # kubectl get deployment -l asya.sh/actor=hello -->

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
  until kubectl logs -l asya.sh/actor=hello -c asya-runtime 2>&1 | tee /dev/stderr | grep -q "greeting"; do
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

Watch the actor scale up to 5 pods (25 messages / 5 messages per pod) using `kubectl get asya hello -w`.

Press `Ctrl+C` to stop watching for pods.


## Add S3 Storage (Optional)

**What you get**: Pipeline completion with result persistence to S3

### 1. Create S3 Buckets

Suppose, we want to save all messages to the buckets `s3://asya-results-bucket` and `s3://asya-errors-bucket`. Note that the bucket name should be globally unique.

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-system \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 s3 mb s3://asya-results-bucket
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 s3 mb s3://asya-errors-bucket
  "
```

### 2. Install Crew Actors

Crew actors handle pipeline completion:

```bash
cat > crew-values.yaml <<EOF
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
            value: "asya-results-bucket"
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
            value: "asya-errors-bucket"
          - name: ASYA_S3_ENDPOINT
            value: "http://localstack.asya-system.svc.cluster.local:4566"
          - name: ASYA_S3_REGION
            value: "us-east-1"
          - name: AWS_ACCESS_KEY_ID
            value: "test"
          - name: AWS_SECRET_ACCESS_KEY
            value: "test"
EOF

helm install asya-crew asya/asya-crew \
  -n default \
  -f crew-values.yaml
```

Your pipeline results are now automatically persisted to S3: whenever an actor finishes processing the last message in the route, 🎭 automatically sends it to `happy-end` actor to persist it on S3. Similarly, error messages will be sent to `error-end`.


## Namespace Architecture

Asya🎭 uses namespace separation to distinguish infrastructure from business logic:

**asya-system namespace** (infrastructure layer):
- Asya🎭 Operator (watches AsyncActors across all namespaces)
- LocalStack / infrastructure services
- KEDA (monitors queues across all namespaces)
- Prometheus / Grafana (when installed)

**Business namespaces** (e.g., default, production):
- Gateway (routes messages to actors in same namespace)
- Gateway PostgreSQL (gateway's envelope tracking database)
- Async actors and flows (your ML/AI workloads)
- Crew actors (happy-end, error-end - part of the pipelines)

**Why this separation?**

Gateway is part of the business logic layer - it exposes your actors as MCP tools and routes messages to actor queues. In multi-tenant deployments, each namespace can have its own gateway instance served by a single operator in asya-system.

## Add Gateway (Optional)

**What you get**: HTTP API, MCP tools, SSE streaming, envelope tracking

### 1. Install PostgreSQL

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: asya-gateway-postgresql
  namespace: default
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
  namespace: default
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
  --namespace default \
  --from-literal=password=asya
```

### 3. Install Gateway

```bash
cat > gateway-values.yaml <<EOF
image:
  repository: ghcr.io/deliveryhero/asya-gateway
  tag: latest

config:
  sqsEndpoint: http://localstack.asya-system.svc.cluster.local:4566
  sqsRegion: us-east-1
  database:
    host: asya-gateway-postgresql.default.svc.cluster.local
    name: asya
    user: asya
    password: asya

env:
- name: AWS_ACCESS_KEY_ID
  value: "test"
- name: AWS_SECRET_ACCESS_KEY
  value: "test"
EOF

helm install asya-gateway asya/asya-gateway \
  -n default \
  -f gateway-values.yaml

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=asya-gateway \
  -n default --timeout=300s
```

### 4. Update Operator for Gateway Integration

```bash
cat >> operator-values.yaml <<EOF
gatewayURL: "http://asya-gateway.default.svc.cluster.local:8080"
EOF

helm upgrade asya-operator asya/asya-operator \
  -n asya-system \
  -f operator-values.yaml
```

### 5. Update Crew for Gateway Reporting

```bash
cat > crew-values.yaml <<EOF
happy-end:
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_GATEWAY_URL
            value: "http://asya-gateway.default.svc.cluster.local:8080"
          - name: ASYA_S3_BUCKET
            value: "asya-results-bucket"
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
            value: "http://asya-gateway.default.svc.cluster.local:8080"
          - name: ASYA_S3_BUCKET
            value: "asya-errors-bucket"
          - name: ASYA_S3_ENDPOINT
            value: "http://localstack.asya-system.svc.cluster.local:4566"
          - name: ASYA_S3_REGION
            value: "us-east-1"
          - name: AWS_ACCESS_KEY_ID
            value: "test"
          - name: AWS_SECRET_ACCESS_KEY
            value: "test"
EOF

helm upgrade asya-crew asya/asya-crew \
  -n default \
  -f crew-values.yaml

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=asya-crew \
  -n default --timeout=300s
```

### 6. Install asya CLI

The Asya CLI provides MCP client tools for calling actors through the gateway:

```bash
pip install git+https://github.com/deliveryhero/asya.git#subdirectory=src/asya-cli
```

### 7. Configure Gateway Tools

Define which actors are exposed as MCP tools. Update gateway values to add a tool for the hello actor:

```bash
cat > gateway-tool-values.yaml <<EOF
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
EOF

helm upgrade asya-gateway asya/asya-gateway \
  -n default \
  -f gateway-values.yaml \
  -f gateway-tool-values.yaml

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=asya-gateway \
  -n default --timeout=300s
```

### 8. Test Gateway Integration

In a separate terminal, port-forward the gateway service to your local machine:

```bash
kubectl port-forward -n default svc/asya-gateway 8080:80
```

Set the MCP URL environment variable:

```bash
export ASYA_CLI_MCP_URL=http://localhost:8080/
```

List available tools:

```bash
asya mcp list
```

Expected output:
```
Available tools:
- hello: Greets users by name
```

Call the hello actor through the gateway:

```bash
asya mcp call hello --name=Asya
```

Expected output will show the envelope ID and completion status.

Stream real-time progress using Server-Sent Events (SSE):

```bash
asya mcp call hello --name=Asya --stream
```

This will show progress updates as the message flows through the pipeline until completion.

Check envelope status by ID:

```bash
asya mcp status <envelope-id>
```

The gateway now provides:
- **MCP HTTP API** for submitting envelopes to actor pipelines
- **SSE streaming** for real-time progress updates
- **Envelope tracking** in PostgreSQL for status queries
- **Tool configuration** for data science teams to call actors

---

## Add Prometheus (Optional)

**What you get**: Metrics collection and observability

### 1. Install Prometheus

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
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

### 3. Configure Asya Dashboard

Create a ConfigMap with the Asya dashboard:

```bash
kubectl create configmap asya-dashboard \
  -n monitoring \
  --from-file=asya-actors.json=https://raw.githubusercontent.com/deliveryhero/asya/refs/heads/main/deploy/grafana-dashboards/asya-actors.json

kubectl label configmap asya-dashboard \
  -n monitoring \
  grafana_dashboard=1
```

The Grafana sidecar will automatically discover and load the dashboard.

### 4. Access Grafana

Port-forward Grafana:

```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
```

Get admin password:

```bash
kubectl get secret -n monitoring prometheus-grafana -o jsonpath='{.data.admin-password}' | base64 -d && echo
```

Login with username `admin` and the password from above.

Open `http://localhost:3003/d/asya-actors-dashboard/asya-actors-dashboard`

The dashboard shows:
- Message throughput and active messages
- Processing and runtime execution duration
- Error rates by reason and type
- Envelope size distribution
- Operator health metrics

### 5. Verify Metrics Collection

Send messages to generate metrics:

```bash
for i in {1..10}; do
  asya mcp call hello --name="User$i"
done
```

In the Grafana dashboard:
- Select **default** namespace and **asya-default-hello** queue
- Watch message rate increase
- See processing duration metrics
- Monitor error rates (should be zero)

You can also query metrics directly in Grafana Explore:
- `asya_actor_processing_duration_seconds{queue="asya-default-hello"}`
- `asya_actor_messages_processed_total{queue="asya-default-hello"}`
- `asya_actor_active_messages`
- `controller_runtime_reconcile_total{controller="asyncactor"}`

## Testing Your Setup

Send a message and watch scaling:

```bash
# Send message
asya mcp call hello --name="Test"

# Watch pods scale
kubectl get pods -l asya.sh/actor=hello -w

# Check logs
POD=$(kubectl get pods -l asya.sh/actor=hello -o name | head -1)
kubectl logs $POD -c asya-runtime
kubectl logs $POD -c asya-sidecar
```

## Alternative: Quick E2E Setup

For rapid testing with all components:

```bash
cd testing/e2e
make up PROFILE=sqs-s3
```

This deploys everything in one command but uses test configurations.

---

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

---

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

---

## Clean Up

To remove components individually:

```bash
# Remove actors
kubectl delete asya --all

# Remove crew
helm uninstall asya-crew -n default

# Remove gateway
helm uninstall asya-gateway -n default
kubectl delete secret asya-gateway-postgresql -n default
kubectl delete deployment asya-gateway-postgresql -n default
kubectl delete service asya-gateway-postgresql -n default

# Remove operator
helm uninstall asya-operator -n asya-system
kubectl delete secret sqs-secret -n asya-system

# Remove KEDA
helm uninstall keda -n keda-system

# Remove LocalStack
helm uninstall localstack -n asya-system

# Remove Prometheus (if installed)
helm uninstall prometheus -n monitoring
```

To remove everything including the cluster:

```bash
kind delete cluster --name asya-local
```

---

**Next**: Choose your path - [Data Scientists](for-data-scientists.md) or [Platform Engineers](for-platform-engineers.md)
