# Asya Operator

Kubernetes operator for deploying Asya actors with automatic sidecar injection and KEDA autoscaling.

> 📄 **Source Code**: [`operator/`](../../operator/)
> 📖 **Developer README**: [`operator/README.md`](../../operator/README.md)

## Overview

The Asya Operator provides a CRD-based approach to deploying actor workloads. Define an `Asya` resource and the operator automatically:

1. Injects the sidecar container into your pod template
2. Creates the workload (Deployment, StatefulSet, or Job)
3. Sets up KEDA autoscaling based on queue depth
4. Configures volumes and environment for socket communication

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      AsyncActor CRD                           │
│  ┌──────────────────────────────────────────────────┐  │
│  │ apiVersion: asya.io/v1alpha1                     │  │
│  │ kind: AsyncActor                                       │  │
│  │ spec:                                            │  │
│  │   queueName: my-queue                           │  │
│  │   workload:                                     │  │
│  │     type: Deployment                            │  │
│  │     template: {...}                             │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
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
│ (with sidecar)   │   (KEDA)     │   │   (KEDA)     │
└──────────────┘   └──────────────┘   └──────────────┘
```

## Why Use the Operator?

**Without Operator** (manual deployment):
```yaml
# 100+ lines of Deployment YAML with:
# - Manual sidecar container configuration
# - Volume mounts for socket
# - Environment variables
# - KEDA ScaledObject
# - TriggerAuthentication
# - ServiceAccount, RBAC
# ...
```

**With Operator**:
```yaml
# ~20 lines
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  queueName: my-queue
  transport:
    type: rabbitmq
  scaling:
    enabled: true
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: runtime
          image: my-actor:latest
```

## Key Benefits

- **Clean API**: Simple, declarative YAML
- **Automatic sidecar injection**: No manual configuration
- **Centralized management**: Update sidecar version globally
- **Multiple workload types**: Deployment, StatefulSet, Job
- **Built-in KEDA integration**: Automatic autoscaling
- **Consistent patterns**: Same approach for all actors

## Installation

### Quick Start (Automated)

```bash
cd examples/deployment-minikube
./deploy.sh      # Includes operator installation
```

### Manual Installation

```bash
# Install CRD
kubectl apply -f operator/config/crd/

# Install operator via Helm
helm install asya-operator deploy/helm-charts/asya-operator \
  -n asya-system --create-namespace

# Verify
kubectl get pods -n asya-system
kubectl get crd asyncactors.asya.io
```

See [`operator/README.md`](../../operator/README.md) for detailed installation instructions.

## Basic Usage

### Simple Actor

```yaml
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: hello-actor
spec:
  queueName: hello-queue

  transport:
    type: rabbitmq
    rabbitmq:
      host: rabbitmq.asya.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-secret
        key: password

  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    queueLength: 5

  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: runtime
          image: asya-runtime:latest
```

Apply:
```bash
kubectl apply -f hello-actor.yaml
```

Verify:
```bash
kubectl get asyas
kubectl describe asya hello-actor
kubectl get deployment hello-actor
kubectl get scaledobject hello-actor
```

## Specification

### Required Fields

- `spec.queueName`: Queue name to consume from
- `spec.transport.type`: Transport type (`rabbitmq`)
- `spec.workload`: Workload template

### Transport Configuration

#### RabbitMQ
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

### Workload Types

#### Deployment (Default)
```yaml
workload:
  type: Deployment
  template:
    spec:
      containers:
      - name: runtime
        image: my-actor:latest
```

#### StatefulSet
```yaml
workload:
  type: StatefulSet
  template:
    spec:
      containers:
      - name: runtime
        image: my-stateful-actor:latest
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

#### Job
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

### Autoscaling Configuration

```yaml
scaling:
  enabled: true
  minReplicas: 0        # Scale to zero when idle
  maxReplicas: 50       # Maximum pod count
  pollingInterval: 10   # Queue polling interval (seconds)
  cooldownPeriod: 60    # Cooldown before scale to zero
  queueLength: 5        # Messages per replica
```

**Scaling Behavior:**
- Queue: 0 messages → 0 replicas (after cooldown)
- Queue: 10 messages → 2 replicas (10/5 = 2)
- Queue: 50 messages → 10 replicas (50/5 = 10, capped at maxReplicas)

### Sidecar Customization

```yaml
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
  - name: ASYA_RUNTIME_TIMEOUT
    value: "10m"
```

## Status Conditions

Check actor status:

```bash
kubectl get asya hello-actor -o yaml
```

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

  scaledObjectRef:
    name: hello-actor
```

## Examples

See [`examples/asyas/`](../../examples/asyas/) for complete examples:

- `simple-actor.yaml` - Basic actor with RabbitMQ
- `statefulset-actor.yaml` - StatefulSet workload
- `multi-container-actor.yaml` - Multiple containers
- `custom-sidecar-actor.yaml` - Custom sidecar configuration
- `no-scaling-actor.yaml` - Disabled autoscaling

## Development

### Build Operator

```bash
cd operator

# Run tests
make test

# Build binary
make build

# Build Docker image
make docker-build IMG=asya-operator:dev
```

Or use automated build:

```bash
# From repository root
./scripts/build-images.sh
```

### Run Locally

```bash
cd operator

# Install CRD
make install

# Run operator locally (connects to current kubeconfig)
make run
```

## Troubleshooting

See [`operator/README.md`](../../operator/README.md#troubleshooting) for:
- Actor not creating workload
- Sidecar not injecting
- KEDA not scaling
- Socket permission issues

## Next Steps

- [Gateway Component](gateway.md) - MCP gateway
- [Sidecar Component](sidecar.md) - Message routing
- [Example Actors](../examples/actors.md) - More examples
- [Deployment Guide](../guides/deployment.md) - Production deployment
