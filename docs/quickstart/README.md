# Getting Started with Asya🎭 (Crossplane Architecture)

This quickstart deploys Asya using **Crossplane Compositions** for infrastructure management
and the **asya-injector webhook** for sidecar injection, replacing the monolithic asya-operator.

## What You'll Learn

- Deploy Crossplane providers and compositions for SQS + KEDA + Kubernetes resources
- Deploy the asya-injector mutating webhook for automatic sidecar injection
- Create your first AsyncActor using a Crossplane claim
- Test autoscaling: scale-from-zero, process messages, scale-to-zero
- Delete an actor and verify all resources are cleaned up

## Prerequisites

- [Docker](https://www.docker.com/get-started/) 24+
- [kubectl](https://kubernetes.io/docs/tasks/tools/) 1.28+
- [Helm](https://helm.sh/docs/intro/install/) 3.12+
- [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) 0.20+
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) (for sending test messages)

## 1. Create Kind Cluster

```bash
kind create cluster --name asya-crossplane --wait 60s
```

## 2. Build and Load Images

From the repository root:

```bash
# Build sidecar
docker build -t asya-sidecar:latest -f src/asya-sidecar/Dockerfile src/asya-sidecar/

# Build injector
docker build -t asya-injector:latest -f src/asya-injector/Dockerfile src/asya-injector/
```

Create a test actor handler:

```bash
mkdir -p /tmp/test-actor

cat > /tmp/test-actor/handler.py <<'PYEOF'
def greet(payload):
    name = payload.get("name", "World")
    return {"greeting": f"Hello, {name}!"}
PYEOF

cat > /tmp/test-actor/Dockerfile <<'DEOF'
FROM python:3.12-slim
WORKDIR /app
COPY handler.py /app/handler.py
ENV ASYA_HANDLER=handler.greet
DEOF

docker build -t test-actor:latest /tmp/test-actor/
```

Load all images into Kind:

```bash
kind load docker-image asya-sidecar:latest asya-injector:latest test-actor:latest \
  --name asya-crossplane
```

## 3. Install Infrastructure

### cert-manager (for webhook TLS)

```bash
kubectl cluster-info --context kind-asya-crossplane
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.17.1/cert-manager.yaml
kubectl wait --for=condition=Available deployment/cert-manager-webhook -n cert-manager --timeout=120s
```

### Crossplane

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace --wait --timeout 120s
```

### KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda --namespace keda --create-namespace --wait --timeout 120s
```

### LocalStack (SQS emulator)

```bash
kubectl create namespace localstack

kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: localstack
  namespace: localstack
spec:
  replicas: 1
  selector:
    matchLabels:
      app: localstack
  template:
    metadata:
      labels:
        app: localstack
    spec:
      containers:
      - name: localstack
        image: localstack/localstack:latest
        ports:
        - containerPort: 4566
        env:
        - name: SERVICES
          value: "sqs"
        - name: DEFAULT_REGION
          value: "us-east-1"
---
apiVersion: v1
kind: Service
metadata:
  name: localstack
  namespace: localstack
spec:
  selector:
    app: localstack
  ports:
  - port: 4566
    targetPort: 4566
EOF

kubectl wait --for=condition=Available deployment/localstack -n localstack --timeout=120s
```

## 4. Install Crossplane Providers

Providers must be installed first so their CRDs are available for the chart:

```bash
kubectl apply -f - <<'EOF'
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: provider-kubernetes-watches
  labels:
    app.kubernetes.io/managed-by: Helm
  annotations:
    meta.helm.sh/release-name: asya-crossplane
    meta.helm.sh/release-namespace: default
spec:
  deploymentTemplate:
    spec:
      template:
        spec:
          containers:
            - name: package-runtime
              args:
                - --enable-watches
---
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-aws-sqs
  labels:
    app.kubernetes.io/managed-by: Helm
  annotations:
    meta.helm.sh/release-name: asya-crossplane
    meta.helm.sh/release-namespace: default
spec:
  package: xpkg.upbound.io/upbound/provider-aws-sqs:v1.19.0
---
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
  labels:
    app.kubernetes.io/managed-by: Helm
  annotations:
    meta.helm.sh/release-name: asya-crossplane
    meta.helm.sh/release-namespace: default
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v0.17.0
  runtimeConfigRef:
    name: provider-kubernetes-watches
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-go-templating
  labels:
    app.kubernetes.io/managed-by: Helm
  annotations:
    meta.helm.sh/release-name: asya-crossplane
    meta.helm.sh/release-namespace: default
spec:
  package: xpkg.upbound.io/crossplane-contrib/function-go-templating:v0.11.3
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-patch-and-transform
  labels:
    app.kubernetes.io/managed-by: Helm
  annotations:
    meta.helm.sh/release-name: asya-crossplane
    meta.helm.sh/release-namespace: default
spec:
  package: xpkg.crossplane.io/crossplane-contrib/function-patch-and-transform:v0.8.2
EOF
```

Wait for all providers and functions to become healthy:

```bash
echo "Waiting for providers..."
until kubectl get providers,functions -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Healthy")].status}{" "}{end}' 2>/dev/null | grep -q "True True True True"; do
  sleep 5
done
echo "All providers healthy"
```

Grant the Kubernetes provider cluster-admin permissions:

```bash
K8S_SA=$(kubectl get providers provider-kubernetes -o jsonpath='{.status.currentRevision}')
kubectl create clusterrolebinding provider-kubernetes-admin \
  --clusterrole=cluster-admin \
  --serviceaccount="crossplane-system:${K8S_SA}"
```

## 5. Create Secrets and ConfigMaps

```bash
# Crossplane AWS credentials (INI format for Upbound providers)
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: aws-creds
  namespace: crossplane-system
type: Opaque
stringData:
  credentials: |
    [default]
    aws_access_key_id = test
    aws_secret_access_key = test
EOF

# KEDA SQS trigger credentials
kubectl create secret generic aws-creds -n default \
  --from-literal=AWS_ACCESS_KEY_ID=test \
  --from-literal=AWS_SECRET_ACCESS_KEY=test

# asya-runtime script (mounted into actor pods)
kubectl create configmap asya-runtime -n default \
  --from-file=asya_runtime.py=src/asya-runtime/asya_runtime.py

# Create happy-end and error-end queues (normally managed by crew actors)
kubectl port-forward -n localstack svc/localstack 4566:4566 &
sleep 3
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
  aws --endpoint-url=http://localhost:4566 --region us-east-1 \
  sqs create-queue --queue-name asya-default-happy-end
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
  aws --endpoint-url=http://localhost:4566 --region us-east-1 \
  sqs create-queue --queue-name asya-default-error-end
kill %1 2>/dev/null
```

## 6. Install Asya Crossplane Chart

```bash
helm install asya-crossplane deploy/helm-charts/asya-crossplane/ \
  -f deploy/helm-charts/asya-crossplane/values-localstack.yaml \
  --set actorNamespace=default
```

Verify the XRD is established:

```bash
kubectl get xrd xasyncactors.asya.sh
# Should show ESTABLISHED=True, OFFERED=True
```

## 7. Install Asya Injector

```bash
helm install asya-injector deploy/helm-charts/asya-injector/ \
  --namespace asya-system --create-namespace \
  --set config.sidecarImage=asya-sidecar:latest \
  --set config.sidecarImagePullPolicy=Never \
  --set config.sqsEndpoint=http://localstack.localstack.svc.cluster.local:4566 \
  --set config.awsCredsSecret=aws-creds \
  --set image.repository=asya-injector \
  --set image.tag=latest \
  --set image.pullPolicy=Never \
  --wait --timeout 180s
```

Verify the webhook is registered:

```bash
kubectl get mutatingwebhookconfigurations
# Should show asya-injector
```

## 8. Deploy Your First Actor

```bash
kubectl apply -f - <<'EOF'
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello
  namespace: default
  labels:
    asya.sh/actor: hello
spec:
  transport: sqs
  region: us-east-1
  providerConfigRef: localstack
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    pollingInterval: 10
    cooldownPeriod: 30
    queueLength: 5
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          image: test-actor:latest
          imagePullPolicy: Never
          env:
          - name: ASYA_HANDLER
            value: handler.greet
          - name: ASYA_HANDLER_MODE
            value: payload
          - name: PYTHONPATH
            value: /app
EOF
```

Wait for resources:

```bash
kubectl get asyncactors -n default
# STATUS should become "Ready" or "Napping"

kubectl get queue.sqs.aws.upbound.io
# SQS queue should show READY=True

kubectl get scaledobject -n default
# ScaledObject should show READY=True
```

## 9. Test Scaling

Send a message to trigger scale-from-zero:

```bash
kubectl port-forward -n localstack svc/localstack 4566:4566 &
sleep 3

AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
  aws --endpoint-url=http://localhost:4566 --region us-east-1 \
  sqs send-message \
  --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/asya-default-hello \
  --message-body '{"id":"test-1","route":{"actors":["hello"],"current":0},"headers":{},"payload":{"name":"Crossplane"}}'

kill %1 2>/dev/null
```

Watch the pod scale up:

```bash
kubectl get pods -n default -w
# Pod should appear with 2/2 containers (runtime + injected sidecar)
```

Check the sidecar logs:

```bash
POD=$(kubectl get pods -n default -l app.kubernetes.io/name=hello -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n default $POD -c asya-sidecar --tail=10
# Should show: "Runtime call completed" and "SQS message sent successfully"
```

After the cooldown period (30s + HPA stabilization), the pod scales back to zero:

```bash
kubectl get deployment hello -n default
# READY should show 0/0
```

## 10. Test Scale-to-N

Send a batch of messages with proper envelope format to trigger multiple replicas:

```bash
kubectl port-forward -n localstack svc/localstack 4566:4566 &
sleep 3

QUEUE_URL=http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/asya-default-hello

for i in $(seq 1 100); do
  AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
    aws --endpoint-url=http://localhost:4566 --region us-east-1 \
    sqs send-message \
    --queue-url "$QUEUE_URL" \
    --message-body "{\"id\":\"batch-$i\",\"route\":{\"actors\":[\"hello\"],\"current\":0},\"headers\":{},\"payload\":{\"name\":\"User-$i\"}}" \
    --no-cli-pager > /dev/null
done

echo "Sent 100 messages"
kill %1 2>/dev/null
```

Watch replicas scale up:

```bash
kubectl get deployment hello -n default -w
# READY should increase beyond 1 (up to maxReplicas=10)
```

After all messages are processed and the cooldown period passes, replicas scale back to zero.

## 11. Test Resilience

Verify that Crossplane re-creates deleted resources:

```bash
# Delete the deployment
kubectl delete deployment hello -n default

# Wait for Crossplane to re-create it (should take a few seconds with watch enabled)
sleep 10
kubectl get deployment hello -n default
# Deployment should exist again

# Delete the ScaledObject
kubectl delete scaledobject hello -n default
sleep 10
kubectl get scaledobject hello -n default
# ScaledObject should exist again
```

## 12. Test Deletion

```bash
kubectl delete asyncactor hello -n default
```

Verify all resources are cleaned up:

```bash
kubectl get queue.sqs.aws.upbound.io           # No resources
kubectl get object.kubernetes.crossplane.io     # No resources
kubectl get deployment -n default               # No resources
kubectl get scaledobject -n default             # No resources
```

## 13. Clean Up

To remove components individually:

```bash
# Remove actors
kubectl delete asyncactor --all -n default

# Remove crew (if installed)
helm uninstall asya-crew -n default

# Remove gateway (if installed)
helm uninstall asya-gateway -n default
kubectl delete secret asya-gateway-postgresql -n default
kubectl delete deployment asya-gateway-postgresql -n default
kubectl delete service asya-gateway-postgresql -n default

# Remove Crossplane and Injector
helm uninstall asya-crossplane
helm uninstall asya-injector -n asya-system

# Remove KEDA
helm uninstall keda -n keda

# Remove LocalStack
kubectl delete namespace localstack

# Remove Prometheus (if installed)
helm uninstall prometheus -n monitoring
```

To remove everything including the cluster:

```bash
kind delete cluster --name asya-crossplane
```

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

Your pipeline results are now automatically persisted to S3: whenever an actor finishes processing the last message in the route, Asya automatically sends it to `happy-end` actor to persist it on S3. Similarly, error messages will be sent to `error-end`.

## Namespace Architecture

Asya uses namespace separation to distinguish infrastructure from business logic:

**asya-system namespace** (infrastructure layer):
- Crossplane + asya-injector (watches AsyncActors across all namespaces)
- LocalStack / infrastructure services
- KEDA (monitors queues across all namespaces)
- Prometheus / Grafana (when installed)

**Business namespaces** (e.g., default, production):
- Gateway (routes messages to actors in same namespace)
- Gateway PostgreSQL (gateway's task tracking database)
- Async actors and flows (your ML/AI workloads)
- Crew actors (happy-end, error-end - part of the pipelines)

**Why this separation?**

Gateway is part of the business logic layer - it exposes your actors as MCP tools and routes messages to actor queues. In multi-tenant deployments, each namespace can have its own gateway instance served by a single injector in asya-system.

## Add Gateway (Optional)

**What you get**: HTTP API, MCP tools, SSE streaming, task tracking

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

Expected output will show the task ID and completion status.

Stream real-time progress using Server-Sent Events (SSE):

```bash
asya mcp call hello --name=Asya --stream
```

This will show progress updates as the message flows through the pipeline until completion.

Check task status by ID:

```bash
asya mcp status <task-id>
```

The gateway now provides:
- **MCP HTTP API** for submitting tasks to actor pipelines
- **SSE streaming** for real-time progress updates
- **Task tracking** in PostgreSQL for status queries
- **Tool configuration** for data science teams to call actors

## Add Prometheus (Optional)

**What you get**: Metrics collection and observability

### 1. Install Prometheus

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
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
- Message size distribution

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

## Production Deployment

For production on AWS, use Crossplane ProviderConfig with IRSA for AWS credentials instead of static credentials. This allows fine-grained IAM permissions for queue management and message operations.

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

- [Core Concepts](../concepts.md) - Actors, messages, sidecars, routing
- [Motivation](../motivation.md) - Why Asya🎭 exists, when to use it
- [Architecture](../architecture/README.md) - Deep dive into system design
- [Examples](https://github.com/deliveryhero/asya/tree/main/examples) - Sample actors and flows

## Architecture Summary

```
                    AsyncActor Claim
                         |
                    XAsyncActor (Composite)
                         |
              +----------+----------+----------+
              |          |          |          |
           SQS Queue  Deployment  ScaledObj  TriggerAuth
           (Crossplane  (Crossplane  (Crossplane  (Crossplane
            AWS)         K8s)         K8s)         K8s)
                         |
                    Pod Creation
                         |
                    Webhook Injection
                         |
              +----------+----------+
              |                     |
         asya-runtime          asya-sidecar
         (user handler)        (message router)
```

- **Crossplane Compositions** manage infrastructure: SQS queues, Deployments, KEDA ScaledObjects
- **asya-injector webhook** injects the sidecar at pod creation time
- **KEDA** handles autoscaling based on SQS queue depth
- Deletion of the AsyncActor claim cascades to all managed resources
