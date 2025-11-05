# Asya Operator

A Kubernetes operator for deploying Asya actors with automatic sidecar injection and KEDA-based autoscaling.

## Overview

The Asya Operator provides a CRD-based approach to deploying actor workloads. Instead of manually creating Deployments with sidecar containers, you define an `Actor` resource and the operator automatically:

1. **Injects the sidecar container** into your pod template
2. **Creates the workload** (Deployment, StatefulSet, or Job)
3. **Sets up KEDA autoscaling** based on queue depth
4. **Configures volumes and environment** for socket communication

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      AsyncActor CRD                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ apiVersion: asya.io/v1alpha1                         │   │
│  │ kind: AsyncActor                                          │   │
│  │ spec:                                                │   │
│  │   queueName: my-queue                               │   │
│  │   transport: {type: sqs}                            │   │
│  │   workload:                                         │   │
│  │     type: Deployment                                │   │
│  │     template: {...}  # Your runtime container       │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
            ┌───────────────────────────┐
            │   Asya Operator           │
            │   (Controller Manager)    │
            └───────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ Deployment   │   │ ScaledObject │   │ TriggerAuth  │
│ (with sidecar│   │   (KEDA)     │   │   (KEDA)     │
│  injected)   │   │              │   │              │
└──────────────┘   └──────────────┘   └──────────────┘
```

## Why Use This Operator?

The Asya operator provides a **declarative, CRD-based** approach to deploying actors:

```yaml
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor
spec:
  queueName: text-processing
  transport:
    type: rabbitmq
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: runtime
          image: my-text-processor:v1.0
          env:
          - name: MODEL_SIZE
            value: large
```

**Key Benefits:**
- **Clean API**: Simple, declarative YAML instead of verbose Deployment manifests
- **Automatic sidecar injection**: No need to manually configure sidecar containers
- **Centralized configuration**: Update sidecar version globally through operator
- **Multiple workload types**: Supports Deployment, StatefulSet, and Job
- **Built-in KEDA integration**: Automatic autoscaling based on queue depth
- **Consistent patterns**: Same approach for all actors in your cluster

## Runtime ConfigMap Management

The operator **automatically manages** the `asya-runtime` ConfigMap containing `asya_runtime.py`. This eliminates the need for manual ConfigMap creation or copy-pasting runtime code.

### How It Works

1. **At startup**, the operator loads `asya_runtime.py` from the configured source
2. **Creates/updates** the `asya-runtime` ConfigMap in the target namespace
3. **Actors automatically use** this ConfigMap (injected as volume mount at `/opt/asya/asya_runtime.py`)

### Configuration

The runtime source is configured via Helm values or environment variables:

**For local development** (default):
```yaml
# values.yaml
runtime:
  source: local
  local:
    path: "../src/asya-runtime/asya_runtime.py"
  namespace: asya
```

**For production** (GitHub releases - assumes public repository):
```yaml
# values.yaml
runtime:
  source: github
  github:
    repo: "deliveryhero/asya"
    version: "v1.0.0"
  namespace: asya
```

**Environment variables**:
- `ASYA_RUNTIME_SOURCE`: `local` or `github`
- `ASYA_RUNTIME_LOCAL_PATH`: Path to local file (for local source)
- `ASYA_RUNTIME_GITHUB_REPO`: GitHub repository (for github source)
- `ASYA_RUNTIME_VERSION`: Release version/tag (for github source)
- `ASYA_RUNTIME_NAMESPACE`: Namespace for ConfigMap

### Benefits

- ✅ **Single source of truth**: No duplicate runtime code
- ✅ **Automatic updates**: Change source, restart operator → ConfigMap updated
- ✅ **Version control**: GitHub releases ensure correct runtime version
- ✅ **Local development**: Easy iteration with local file watching

### Troubleshooting

Check operator logs for runtime loading issues:
```bash
kubectl logs -n asya-system deploy/asya-operator | grep runtime
```

Verify ConfigMap was created:
```bash
kubectl get configmap asya-runtime -n asya
kubectl describe configmap asya-runtime -n asya
```

## Installation

### Prerequisites

- Kubernetes 1.23+
- KEDA 2.0+ installed (optional, required for autoscaling)
- Helm 3.0+

### Quick Start: Automated Full Stack

**Recommended for testing** - deploys complete stack with infrastructure:

```bash
cd ../examples/deployment-minikube
./deploy.sh      # Automated deployment (~5-10 minutes)
./test-e2e.sh        # Verify deployment
```

### Manual Installation: Framework Only

Install just the operator without infrastructure:

```bash
# Install CRD
kubectl apply -f config/crd/asya.io_asyas.yaml

# Install operator via Helm
helm install asya-operator ../deploy/helm-charts/asya-operator \
  -n asya-system --create-namespace
```

### Verify Installation

```bash
# Check operator is running
kubectl get pods -n asya-system

# Check CRD is installed
kubectl get crd asyncactors.asya.io
```

## Quick Start

### 1. Create an Asya

Create a file `my-actor.yaml`:

```yaml
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: hello-actor
  namespace: default
spec:
  # Queue configuration
  queueName: hello-queue

  # Transport (sqs or rabbitmq)
  transport:
    type: rabbitmq
    rabbitmq:
      host: rabbitmq.rabbitmq.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-secret
        key: password

  # KEDA autoscaling
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    queueLength: 5

  # Your workload
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: runtime
          image: asya-runtime:latest
          resources:
            limits:
              cpu: 1000m
              memory: 1Gi
```

Apply it:

```bash
kubectl apply -f my-actor.yaml
```

### 2. Check Status

```bash
# List actors
kubectl get asyas

# Get details
kubectl describe asya hello-actor

# Check created resources
kubectl get deployment hello-actor
kubectl get scaledobject hello-actor
```

### 3. Monitor Scaling

```bash
# Watch HPA
kubectl get hpa -w

# Check KEDA metrics
kubectl get scaledobject hello-actor -o yaml
```

## Actor Specification

### Full Example

```yaml
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: advanced-actor
  namespace: production
spec:
  # Required: Queue name
  queueName: my-processing-queue

  # Required: Transport configuration
  transport:
    type: sqs  # or rabbitmq
    sqs:
      region: us-east-1
      queueBaseUrl: https://sqs.us-east-1.amazonaws.com/123456789
      visibilityTimeout: 300
      waitTimeSeconds: 20

  # Optional: Sidecar configuration
  sidecar:
    image: asya-sidecar:v2.0
    imagePullPolicy: Always
    resources:
      limits:
        cpu: 500m
        memory: 256Mi
      requests:
        cpu: 100m
        memory: 64Mi
    env:
    - name: CUSTOM_VAR
      value: custom-value

  # Optional: Socket configuration
  socket:
    path: /tmp/sockets/app.sock
    maxSize: "10485760"

  # Optional: Timeout configuration
  timeout:
    processing: 300
    gracefulShutdown: 30

  # Optional: Scaling configuration
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 50
    pollingInterval: 10
    cooldownPeriod: 60
    queueLength: 5

  # Required: Workload template
  workload:
    type: Deployment  # or StatefulSet, Job
    replicas: 1  # ignored if scaling.enabled=true
    template:
      metadata:
        labels:
          app: my-app
          version: v1
      spec:
        containers:
        - name: runtime
          image: my-runtime:v1.0
          env:
          - name: APP_CONFIG
            value: production
          resources:
            limits:
              cpu: 2000m
              memory: 2Gi
            requests:
              cpu: 500m
              memory: 512Mi
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spec.queueName` | string | ✅ | Queue name to consume from |
| `spec.transport.type` | enum | ✅ | `sqs` or `rabbitmq` |
| `spec.transport.sqs` | object | ⚠️ | SQS config (required if type=sqs) |
| `spec.transport.rabbitmq` | object | ⚠️ | RabbitMQ config (required if type=rabbitmq) |
| `spec.sidecar` | object | ❌ | Sidecar container config |
| `spec.socket` | object | ❌ | Unix socket config |
| `spec.timeout` | object | ❌ | Timeout settings |
| `spec.scaling` | object | ❌ | KEDA autoscaling config |
| `spec.workload` | object | ✅ | Workload template |

## Transport Configuration

### SQS

```yaml
transport:
  type: sqs
  sqs:
    region: us-east-1
    queueBaseUrl: https://sqs.us-east-1.amazonaws.com/123456789
    visibilityTimeout: 300
    waitTimeSeconds: 20
```

**Authentication:** Uses IAM roles via pod identity (IRSA in EKS).

### RabbitMQ

```yaml
transport:
  type: rabbitmq
  rabbitmq:
    host: rabbitmq.default.svc.cluster.local
    port: 5672
    username: admin
    passwordSecretRef:
      name: rabbitmq-credentials
      key: password
```

Create the secret:

```bash
kubectl create secret generic rabbitmq-credentials \
  --from-literal=password=your-password
```

## Workload Types

### Deployment (Default)

Best for stateless, long-running actors:

```yaml
workload:
  type: Deployment
  template:
    spec:
      containers:
      - name: runtime
        image: my-actor:latest
```

### StatefulSet

For actors requiring stable identity or persistent storage:

```yaml
workload:
  type: StatefulSet
  template:
    spec:
      containers:
      - name: runtime
        image: my-stateful-actor:latest
        volumeMounts:
        - name: data
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

### Job

For one-off or batch processing:

```yaml
workload:
  type: Job
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: runtime
        image: my-batch-processor:latest
```

## KEDA Autoscaling

The operator automatically creates a KEDA `ScaledObject` when `scaling.enabled: true`.

### How It Works

1. **Queue Monitoring:** KEDA polls the queue every `pollingInterval` seconds
2. **Scaling Decision:** If queue length > (queueLength × replicas), scale up
3. **Scale to Zero:** When queue is empty for `cooldownPeriod`, scale to 0
4. **Fast Scale Up:** Uses aggressive policies for quick response to load

### Scaling Policies

**Scale Up:**
- 100% increase every 15 seconds, OR
- +4 pods every 15 seconds
- Whichever is higher

**Scale Down:**
- 50% decrease every 15 seconds
- 60 second stabilization window

### Example Scaling Behavior

```
Queue: 0 messages  → 0 replicas (scale to zero)
Queue: 10 messages → 2 replicas (10/5 = 2)
Queue: 50 messages → 10 replicas (50/5 = 10, capped at maxReplicas)
Queue: 0 messages  → Wait 60s → 0 replicas
```

## Status Conditions

The Actor status includes conditions for observability:

```yaml
status:
  conditions:
  - type: WorkloadReady
    status: "True"
    reason: WorkloadCreated
    message: Deployment successfully created
  - type: ScalingReady
    status: "True"
    reason: ScaledObjectCreated
    message: KEDA ScaledObject successfully created

  workloadRef:
    apiVersion: apps/v1
    kind: Deployment
    name: hello-actor
    namespace: default

  scaledObjectRef:
    name: hello-actor
    namespace: default

  observedGeneration: 2
```

Check conditions:

```bash
kubectl get asya hello-actor -o jsonpath='{.status.conditions}'
```

## Development

### Build the Operator

**Automated build** (builds all framework images):
```bash
# From repository root
./scripts/build-images.sh

# Build and load into Minikube
./scripts/load-images-minikube.sh --build
```

**Manual build**:
```bash
cd operator

# Download dependencies
go mod download

# Run tests
make test

# Build binary
make build

# Build Docker image
make docker-build IMG=asya-operator:dev

# Load into Minikube
minikube image load asya-operator:dev
```

### Run Locally

```bash
# Install CRD
make install

# Run operator locally (connects to your current kubeconfig)
make run
```

### Generate Code

After modifying API types:

```bash
# Generate DeepCopy methods
make generate

# Update CRD manifests
# (CRDs are hand-written, no generation needed)
```

## Troubleshooting

### Actor Not Creating Workload

```bash
# Check operator logs
kubectl logs -n asya-system deploy/asya-operator -f

# Check Actor status
kubectl describe asya <name>

# Check events
kubectl get events --sort-by='.lastTimestamp'
```

### Sidecar Not Injecting

The operator injects the sidecar as the **first** container. Verify:

```bash
kubectl get deployment <actor-name> -o jsonpath='{.spec.template.spec.containers[0].name}'
# Should output: sidecar
```

### KEDA Not Scaling

```bash
# Check ScaledObject
kubectl get scaledobject <actor-name> -o yaml

# Check KEDA operator logs
kubectl logs -n keda -l app=keda-operator -f

# Check HPA
kubectl get hpa
kubectl describe hpa keda-hpa-<actor-name>
```

### Socket Permission Issues

Ensure both containers run with compatible security contexts:

```yaml
workload:
  template:
    spec:
      securityContext:
        fsGroup: 1000
      containers:
      - name: runtime
        securityContext:
          runAsUser: 1000
```

## Best Practices

### 1. Resource Limits

Always set resource limits for both runtime and sidecar:

```yaml
sidecar:
  resources:
    limits:
      cpu: 500m
      memory: 256Mi
    requests:
      cpu: 100m
      memory: 64Mi

workload:
  template:
    spec:
      containers:
      - name: runtime
        resources:
          limits:
            cpu: 2000m
            memory: 2Gi
```

### 2. Queue Length Tuning

Set `queueLength` based on your processing time:

- Fast processing (< 1s): `queueLength: 10`
- Medium processing (1-10s): `queueLength: 5`
- Slow processing (> 10s): `queueLength: 1-2`

### 3. Graceful Shutdown

Set `timeout.gracefulShutdown` longer than your max processing time:

```yaml
timeout:
  processing: 300  # 5 minutes
  gracefulShutdown: 330  # 5.5 minutes (10% buffer)
```

### 4. Labels and Annotations

Add labels for better organization:

```yaml
metadata:
  labels:
    app: my-app
    team: data-processing
    environment: production
```

### 5. Monitoring

Use Prometheus metrics from the operator:

```bash
kubectl port-forward -n asya-system svc/asya-operator-metrics 8080:8080
curl localhost:8080/metrics
```

## Operator vs Manual Deployment

Using the operator vs manually creating Deployments with sidecars:

| Aspect | With Operator | Manual Deployment |
|--------|---------------|-------------------|
| **YAML Complexity** | ~20 lines | ~100+ lines |
| **Sidecar Injection** | Automatic | Manual configuration |
| **Updates** | Change operator config once | Update every deployment |
| **KEDA Integration** | Automatic | Manual ScaledObject creation |
| **Consistency** | Enforced by operator | Manual per deployment |
| **Learning Curve** | Learn CRD API | Learn full K8s resources |

The operator approach is **recommended for production** use with multiple actors.

## Contributing

See the main [CLAUDE.md](../CLAUDE.md) for project structure.

### Project Structure

```
operator/
├── api/v1alpha1/           # API type definitions
│   ├── asya_types.go
│   └── groupversion_info.go
├── cmd/main.go             # Operator entry point
├── internal/controller/    # Controllers
│   ├── asya_controller.go # Main reconciler
│   └── keda.go            # KEDA resource creation
├── config/crd/            # CRD manifests
│   └── asya.io_asyas.yaml
├── Dockerfile
├── Makefile
└── go.mod
```

## License

See main project LICENSE.
