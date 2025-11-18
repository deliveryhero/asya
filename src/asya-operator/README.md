# Asya🎭 Operator

Kubernetes operator for deploying async actors with automatic sidecar injection and KEDA autoscaling.

## Overview

Define an `AsyncActor` resource, the operator automatically:

1. Injects sidecar container
2. Creates workload (Deployment or StatefulSet)
3. Sets up KEDA autoscaling
4. Configures volumes and environment

## What you get

- **~20 lines vs ~100+ lines** of YAML (automatic sidecar injection)
- **Centralized management**: Update sidecar globally
- **Built-in autoscaling**: KEDA integration included
- **Multiple workload kinds**: Deployment or StatefulSet

## Installation

### Prerequisites

- Kubernetes 1.23+
- KEDA 2.0+ (optional, required for autoscaling)
- Helm 3.0+

### Quick Start (Automated)

**Recommended** - deploys complete stack with infrastructure:

```bash
cd testing/e2e
make up              # Full stack (~5-10 minutes)
make trigger-tests   # Verify deployment
```

### Manual Installation

Install framework only:

```bash
# Install CRD
kubectl apply -f src/asya-operator/config/crd/asya.sh_asyas.yaml

# Install operator
helm install asya-operator deploy/helm-charts/asya-operator \
  -n asya-system --create-namespace

# Verify
kubectl get pods -n asya-system
kubectl get crd asyncactors.asya.sh
```

## Quick Start

### 1. Create an AsyncActor

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello-actor
spec:
  # Actor name is automatically used as the queue name
  transport: rabbitmq

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
          image: asya-runtime:latest
          resources:
            limits:
              cpu: 1000m
              memory: 1Gi
```

Apply:
```bash
kubectl apply -f my-actor.yaml
```

### 2. Check Status

```bash
kubectl get asyas
kubectl get asyas -o wide
kubectl describe asya hello-actor
```

See [Monitoring AsyncActors](#monitoring-asyncactors) for detailed column descriptions.

## Runtime ConfigMap Management

The operator automatically manages the `asya-runtime` ConfigMap containing `asya_runtime.py`.

**Configuration** (via Helm values):

```yaml
# Local development (default)
runtime:
  source: local
  local:
    path: "../src/asya-runtime/asya_runtime.py"
  namespace: asya

# Production (GitHub releases)
runtime:
  source: github
  github:
    repo: "deliveryhero/asya"
    version: "v1.0.0"
  namespace: asya
```

**Environment variables**:
- `ASYA_RUNTIME_SOURCE`: `local` or `github`
- `ASYA_RUNTIME_LOCAL_PATH`: Path to local file
- `ASYA_RUNTIME_GITHUB_REPO`: GitHub repository
- `ASYA_RUNTIME_VERSION`: Release version/tag
- `ASYA_RUNTIME_NAMESPACE`: Namespace for ConfigMap

**Verify**:
```bash
kubectl get configmap asya-runtime -n asya
```

See [RUNTIME_CONFIGMAP.md](RUNTIME_CONFIGMAP.md) for detailed configuration.

## Key Fields

### Transport Configuration

Transports are configured once at operator installation time in `deploy/helm-charts/asya-operator/values.yaml`. AsyncActors reference transports by name.

**Operator configuration** (values.yaml):

```yaml
# RabbitMQ transport
transports:
  rabbitmq:
    enabled: true
    type: rabbitmq
    config:
      host: rabbitmq.default.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-credentials
        key: password

  # SQS transport
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
      queueBaseUrl: https://sqs.us-east-1.amazonaws.com/123456789
      visibilityTimeout: 300
      waitTimeSeconds: 20
```

**AsyncActor usage** (just reference by name):

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  transport: rabbitmq  # Reference to operator-configured transport
  # ... rest of spec
```

**Create secrets for RabbitMQ**:
```bash
kubectl create secret generic rabbitmq-credentials \
  --from-literal=password=your-password
```

**Note**: SQS uses IAM roles via pod identity (IRSA in EKS).

### Workload Types

**Deployment** (default):
```yaml
workload:
  kind: Deployment
  template:
    spec:
      containers:
      - name: asya-runtime
        image: my-actor:latest
```

**StatefulSet** (persistent storage):
```yaml
workload:
  kind: StatefulSet
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

### KEDA Autoscaling

Automatically creates ScaledObject when `scaling.enabled: true`.

**How it works**:
1. KEDA polls queue every `pollingInterval` seconds
2. If queue length > (queueLength × replicas), scale up
3. When queue empty for `cooldownPeriod`, scale to 0

**Configuration**:
```yaml
scaling:
  enabled: true
  minReplicas: 0
  maxReplicas: 50
  pollingInterval: 10
  cooldownPeriod: 60
  queueLength: 5
```

**Example behavior**:
```
Queue: 0 messages  → 0 replicas
Queue: 10 messages → 2 replicas (10/5 = 2)
Queue: 50 messages → 10 replicas (capped at maxReplicas)
```

## Monitoring AsyncActors

### kubectl Output

**Default view** - Essential operational status:
```bash
kubectl get asyncactor
```
```
NAME         READY   STATUS        REPLICAS  MIN  MAX  LAST-SCALE       AGE
my-actor     3/3     Ready         5/5       0    10   2m ago (up)      1h
slow-actor   1/3     NoTransport   0/0       0    10   5h ago (down)    2d
new-actor    3/3     Ready         3/5       0    10   30s ago (up)     5m
manual-one   2/2     Ready         3/3       0    10   -                3d
broken       2/3     NoScaling     1/1       0    10   1h ago (up)      2h
```

**Wide view** - Additional infrastructure details:
```bash
kubectl get asyncactor -o wide
```
```
NAME        READY  STATUS        REPLICAS  MIN  MAX  LAST-SCALE      AGE  ASYA_TRANSPORT  WORKLOAD    SCALING
my-actor    3/3    Ready         5/5       0    10   2m ago (up)     1h   rabbitmq   Deployment  KEDA
slow-actor  1/3    NoTransport   0/0       0    10   5h ago (down)   2d   rabbitmq   Deployment  KEDA
manual-one  2/2    Ready         3/3       0    10   -               3d   rabbitmq   Deployment  Manual
```

### Column Reference

| Column | Description | Example Values |
|--------|-------------|----------------|
| **READY** | Ready conditions / total | `3/3`, `2/3`, `2/2` |
| **STATUS** | Priority-based condition status | `Ready`, `NoTransport`, `NoWorkload`, `NoScaling` |
| **REPLICAS** | Current / desired replicas | `5/5`, `3/10`, `0/0` |
| **MIN** | Minimum replicas (scaling config) | `0`, `1` |
| **MAX** | Maximum replicas (scaling config) | `10`, `50` |
| **LAST-SCALE** | Time since last scaling event | `5m ago (up)`, `2h ago (down)`, `-` |
| **AGE** | Time since actor created | `5m`, `1h`, `2d` |
| **ASYA_TRANSPORT** ¹ | Queue transport type | `rabbitmq`, `sqs` |
| **WORKLOAD** ¹ | Kubernetes workload kind | `Deployment`, `StatefulSet` |
| **SCALING** ¹ | Scaling mode | `KEDA`, `Manual` |

¹ Wide view only (`-o wide`)

### Understanding Column Values

**READY** - Condition health fraction:
- `3/3` - All 3 conditions healthy (TransportReady, WorkloadReady, ScalingReady)
- `2/3` - 2 out of 3 conditions healthy
- `2/2` - Manual scaling mode (only TransportReady, WorkloadReady apply)

**STATUS** - Shows most critical issue (priority-based):
- `Ready` - All conditions are True
- `NoTransport` - Transport configuration invalid/failed (highest priority)
- `NoWorkload` - Deployment/StatefulSet creation failed
- `NoScaling` - KEDA ScaledObject creation failed (lowest priority)

**REPLICAS** - Scaling state:
- `5/5` - Stable at desired capacity (current = desired)
- `3/10` - Scaling up in progress (pods starting)
- `10/5` - Scaling down in progress (pods terminating)
- `0/0` - No replicas running or desired

**LAST-SCALE** - Scaling activity indicator:
- `5m ago (up)` - Scaled up 5 minutes ago (replicas increased)
- `2h ago (down)` - Scaled down 2 hours ago (replicas decreased)
- `-` - Never scaled (new actor or static replicas)

### Status Conditions

Check detailed condition status:
```bash
kubectl get asyncactor my-actor -o jsonpath='{.status.conditions}' | jq
```

Available conditions:
- **TransportReady** - Transport configuration validated
- **WorkloadReady** - Deployment/StatefulSet created successfully
- **ScalingReady** - KEDA ScaledObject created (only when scaling enabled)

### Status Fields Reference

Full status field descriptions:

| Field | Type | Description |
|-------|------|-------------|
| `readySummary` | string | Ready conditions count (e.g., "3/3") - displayed as READY |
| `status` | string | Priority-based status ("Ready", "NoTransport", etc.) - displayed as STATUS |
| `replicasSummary` | string | Current/desired replicas (e.g., "5/10") - displayed as REPLICAS |
| `conditions` | array | Kubernetes standard conditions |
| `replicas` | int32 | Current running replicas from workload (internal) |
| `desiredReplicas` | int32 | Desired replicas from KEDA HPA (internal) |
| `lastScaleTime` | timestamp | When replicas last changed |
| `lastScaleDirection` | string | "up", "down", or empty |
| `lastScaleFormatted` | string | Human-readable last scale (e.g., "5m ago (up)") - displayed as LAST-SCALE |
| `scalingMode` | string | "KEDA" or "Manual" - displayed in wide view as SCALING |
| `workloadRef` | object | Reference to created Deployment/StatefulSet |
| `scaledObjectRef` | object | Reference to KEDA ScaledObject |
| `observedGeneration` | int64 | Last processed spec generation |

### Troubleshooting with kubectl

**Check why actor is not ready**:
```bash
kubectl get asyncactor my-actor -o jsonpath='{.status.conditions[?(@.status=="False")]}'
```

**Monitor scaling activity**:
```bash
watch kubectl get asyncactor
```

**View scaling history** (via KEDA HPA):
```bash
kubectl get hpa keda-hpa-my-actor -o yaml
```

**Check workload status**:
```bash
kubectl get deployment my-actor
kubectl get pods -l asya.sh/asya=my-actor
```

## Full Specification

See [examples/asyas/](../../examples/asyas/) for complete examples:
- `simple.yaml` - Basic actor
- `statefulset.yaml` - Persistent storage
- `multi-container.yaml` - Multiple containers
- `advanced.yaml` - All features

**Field reference**:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spec.transport` | string | ✅ | Transport name (configured in operator) |
| `spec.sidecar` | object | ❌ | Sidecar container config |
| `spec.socket` | object | ❌ | Unix socket config |
| `spec.timeout` | object | ❌ | Timeout settings |
| `spec.scaling` | object | ❌ | KEDA autoscaling config |
| `spec.workload` | object | ✅ | Workload template |

## Troubleshooting

**Actor not creating workload**:
```bash
kubectl logs -n asya-system deploy/asya-operator -f
kubectl describe asya <name>
```

**KEDA not scaling**:
```bash
kubectl get scaledobject <actor-name> -o yaml
kubectl logs -n keda -l app=keda-operator -f
kubectl get hpa
```

**Socket permission issues**:
```yaml
workload:
  template:
    spec:
      securityContext:
        fsGroup: 1000
      containers:
      - name: asya-runtime
        securityContext:
          runAsUser: 1000
```

**Runtime ConfigMap issues**:
```bash
kubectl logs -n asya-system deploy/asya-operator | grep runtime
kubectl describe configmap asya-runtime -n asya
```

## Best Practices

### Resource Limits

Always set limits for both containers:
```yaml
sidecar:
  resources:
    limits: {cpu: 500m, memory: 256Mi}
    requests: {cpu: 100m, memory: 64Mi}

workload:
  template:
    spec:
      containers:
      - name: asya-runtime
        resources:
          limits: {cpu: 2000m, memory: 2Gi}
```

### Queue Length Tuning

- Fast processing (< 1s): `queueLength: 10`
- Medium (1-10s): `queueLength: 5`
- Slow (> 10s): `queueLength: 1-2`

### Graceful Shutdown

Set `timeout.gracefulShutdown` > max processing time:
```yaml
timeout:
  processing: 300
  gracefulShutdown: 330  # 10% buffer
```

## Development

**Automated build** (builds all framework images):
```bash
./src/build-images.sh
./scripts/load-images-minikube.sh --build
```

**Manual build**:
```bash
cd operator
go mod download
make test
make build
make docker-build IMG=asya-operator:dev
minikube image load asya-operator:dev
```

**Run locally**:
```bash
make install  # Install CRD
make run      # Run operator locally
```

**Generate code** (after modifying API types):
```bash
make generate  # Generate DeepCopy methods
```

## Project Structure

```
operator/
├── api/v1alpha1/           # API type definitions
├── cmd/main.go             # Operator entry point
├── internal/controller/    # Controllers
│   ├── asya_controller.go  # Main reconciler
│   └── keda.go             # KEDA resource creation
└── config/crd/             # CRD manifests
```

See [CLAUDE.md](../CLAUDE.md) for full project structure.
