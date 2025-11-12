# Asya🎭 Operator Helm Chart

This Helm chart deploys the Asya🎭 Operator, which manages AsyncActor custom resources in a Kubernetes cluster.

## Overview

The Asya🎭 Operator is a cluster-scoped controller that:
- Watches AsyncActor CRDs across all namespaces
- Automatically injects sidecar containers for message queue consumption
- Creates and manages Deployments, StatefulSets, or Jobs based on actor configuration
- Sets up KEDA ScaledObjects for event-driven autoscaling
- Manages the asya_runtime.py ConfigMap for actor runtime initialization

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- AsyncActor CRDs installed (`kubectl apply -f src/asya-operator/config/crd/`)

### For SQS Transport (EKS only)

If using SQS transport, create two IAM roles before installing the operator:

1. **Operator role** (`asya-operator`) - for queue management (create/delete queues)
2. **Shared actor role** (`asya-actor`) - for message send/receive (used by all actors)

See `/AUTH_SQS.md` for detailed IAM setup instructions.

## Namespace Convention

**IMPORTANT**: The operator should always be deployed to the `asya-system` namespace following Kubernetes conventions for infrastructure components.

```bash
# ✓ Correct - operator in asya-system
helm install asya-operator deploy/helm-charts/asya-operator \
  --create-namespace \
  --namespace asya-system

# ✗ Incorrect - do not deploy to other namespaces
helm install asya-operator ... -n asya  # Wrong!
```

The operator will manage AsyncActor resources in **all namespaces**, typically:
- `asya` - Production workloads (gateway, actors)
- `asya-staging` - Staging environment
- `asya-dev` - Development environment
- `asya-e2e` - E2E testing

## Installing the Chart

### Basic Installation

```bash
# Install CRDs first (if not already installed)
kubectl apply -f src/asya-operator/config/crd/

# Install operator
helm install asya-operator deploy/helm-charts/asya-operator \
  --create-namespace \
  --namespace asya-system
```

### Installation with Custom Runtime Source

#### Option 1: Local Development (mount runtime from host)

```bash
helm install asya-operator deploy/helm-charts/asya-operator \
  --namespace asya-system \
  --set runtime.source=local \
  --set runtime.local.path=/etc/asya-runtime/asya_runtime.py \
  --set runtime.namespace=asya
```

#### Option 2: GitHub Releases (production)

```bash
helm install asya-operator deploy/helm-charts/asya-operator \
  --namespace asya-system \
  --set runtime.source=github \
  --set runtime.github.repo=deliveryhero/asya \
  --set runtime.github.version=v1.0.0 \
  --set runtime.namespace=asya
```

## Configuration

### Core Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of operator replicas | `1` |
| `image.repository` | Operator image repository | `asya-operator` |
| `image.tag` | Operator image tag | `latest` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |

### RBAC Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `rbac.create` | Create RBAC resources (ClusterRole, ClusterRoleBinding) | `true` |
| `serviceAccount.create` | Create ServiceAccount | `true` |
| `serviceAccount.name` | ServiceAccount name | `""` (auto-generated) |

### Runtime ConfigMap Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `runtime.source` | Runtime source type: `local` or `github` | `local` |
| `runtime.local.path` | Path to asya_runtime.py (for local source) | `../src/asya-runtime/asya_runtime.py` |
| `runtime.github.repo` | GitHub repository (owner/repo) | `deliveryhero/asya` |
| `runtime.github.version` | GitHub release version/tag | `""` |
| `runtime.namespace` | Namespace to create runtime ConfigMap | `asya` |

**IMPORTANT**: `runtime.namespace` should be set to the namespace where your actors will run (typically `asya`), **not** `asya-system`.

### Transport Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `transports.rabbitmq.enabled` | Enable RabbitMQ transport | `true` |
| `transports.rabbitmq.config.host` | RabbitMQ host | `rabbitmq.default.svc.cluster.local` |
| `transports.sqs.enabled` | Enable SQS transport | `false` |
| `transports.sqs.config.region` | AWS region | `us-east-1` |
| `transports.sqs.config.actorRoleArn` | Shared IAM role ARN for actors (IRSA) | `""` |
| `serviceAccount.annotations` | Operator ServiceAccount annotations (for IRSA) | `{}` |

**SQS Example**:
```bash
helm install asya-operator deploy/helm-charts/asya-operator \
  -n asya-system --create-namespace \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"="$OPERATOR_ROLE_ARN" \
  --set transports.sqs.enabled=true \
  --set transports.sqs.config.region=us-east-1 \
  --set transports.sqs.config.actorRoleArn="$ACTORS_ROLE_ARN"
```

### Sidecar Defaults

| Parameter | Description | Default |
|-----------|-------------|---------|
| `sidecar.image` | Sidecar image for actors | `asya-sidecar:latest` |
| `sidecar.defaultResources.limits.cpu` | CPU limit | `500m` |
| `sidecar.defaultResources.limits.memory` | Memory limit | `256Mi` |
| `sidecar.defaultResources.requests.cpu` | CPU request | `100m` |
| `sidecar.defaultResources.requests.memory` | Memory request | `64Mi` |

### Leader Election

| Parameter | Description | Default |
|-----------|-------------|---------|
| `leaderElection.enabled` | Enable leader election (recommended for HA) | `true` |

### Metrics

| Parameter | Description | Default |
|-----------|-------------|---------|
| `metrics.enabled` | Enable Prometheus metrics | `true` |
| `metrics.port` | Metrics server port | `8080` |

### Health Probes

| Parameter | Description | Default |
|-----------|-------------|---------|
| `health.port` | Health probe port | `8081` |

## Architecture

The operator follows the standard Kubernetes operator pattern:

```
Cluster Architecture:

asya-system/              # Infrastructure namespace
└── asya-operator         # Operator pod (ClusterRole permissions)
    └── watches: AsyncActor resources in ALL namespaces

asya/                     # Application namespace
├── asya-gateway          # MCP gateway
├── asya-runtime          # ConfigMap with asya_runtime.py (created by operator)
├── foo-actor-1          # AsyncActor resource
│   ├── Deployment        # Created by operator
│   │   └── Pod
│   │       ├── runtime (user container)
│   │       └── sidecar (injected by operator)
│   └── ScaledObject      # KEDA autoscaling (created by operator)
└── foo-actor-2          # Another actor
    └── ...

Other namespaces:
├── asya-staging/        # Staging workloads
├── asya-dev/           # Development workloads
└── asya-e2e/          # E2E testing
```

## RBAC Permissions

The operator requires cluster-wide permissions:

- **AsyncActor CRDs**: Full CRUD + status updates
- **Deployments/StatefulSets/Jobs**: Full CRUD
- **KEDA ScaledObjects/TriggerAuthentications**: Full CRUD
- **ConfigMaps**: Full CRUD (for runtime ConfigMap)
- **Secrets**: Read-only (for transport credentials)
- **Leases**: Full CRUD (for leader election)

See `templates/rbac.yaml` for the complete ClusterRole definition.

## Verifying Installation

### Check operator status

```bash
kubectl get pods -n asya-system
kubectl logs -n asya-system -l app.kubernetes.io/name=asya-operator
```

### Check runtime ConfigMap creation

```bash
# Runtime ConfigMap should be created in the namespace specified by runtime.namespace
kubectl get configmap -n asya asya-runtime
kubectl describe configmap -n asya asya-runtime
```

### Create a test AsyncActor

```bash
# Create a test actor in the 'asya' namespace
cat <<EOF | kubectl apply -f -
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: test-actor
  namespace: asya
spec:
  transport: rabbitmq
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
        - name: asya-runtime
          image: python:3.13-slim
          env:
          - name: ASYA_HANDLER
            value: "handlers.echo"
EOF

# Verify the operator created the Deployment
kubectl get deployment -n asya test-actor
kubectl get pods -n asya -l app=test-actor
```

## Upgrading the Chart

```bash
helm upgrade asya-operator deploy/helm-charts/asya-operator \
  --namespace asya-system \
  --reuse-values
```

**Note**: Upgrading the operator will reconcile the runtime ConfigMap. Existing actors will pick up the new runtime on pod restart.

## Uninstalling the Chart

```bash
# Uninstall operator
helm uninstall asya-operator -n asya-system

# Optional: Delete CRDs (this will delete ALL AsyncActor resources!)
kubectl delete crd asyncactors.asya.sh
```

**WARNING**: Deleting the operator will stop reconciliation of AsyncActor resources, but existing Deployments/StatefulSets will continue running until manually deleted.

## Multi-Environment Deployment

### Production Setup

```bash
# Cluster 1: Production
helm install asya-operator deploy/helm-charts/asya-operator \
  -n asya-system \
  --set runtime.source=github \
  --set runtime.github.repo=deliveryhero/asya \
  --set runtime.github.version=v1.2.0 \
  --set runtime.namespace=asya
```

### Staging Setup

```bash
# Cluster 2: Staging
helm install asya-operator deploy/helm-charts/asya-operator \
  -n asya-system \
  --set runtime.source=github \
  --set runtime.github.repo=deliveryhero/asya \
  --set runtime.github.version=v1.3.0-rc1 \
  --set runtime.namespace=asya-staging
```

### E2E Testing Setup

```bash
# Cluster 3: E2E Tests (Kind/Minikube)
helm install asya-operator deploy/helm-charts/asya-operator \
  -n asya-system \
  --set runtime.source=local \
  --set runtime.local.path=/etc/asya-runtime/asya_runtime.py \
  --set runtime.namespace=asya-e2e
```

## Troubleshooting

### Operator not starting

Check operator logs:
```bash
kubectl logs -n asya-system -l app.kubernetes.io/name=asya-operator
```

Common issues:
- CRDs not installed: `kubectl apply -f src/asya-operator/config/crd/`
- RBAC permissions: Verify ClusterRole and ClusterRoleBinding exist
- Image pull errors: Check `imagePullSecrets` configuration

### Runtime ConfigMap not created

Check operator logs for reconciliation errors:
```bash
kubectl logs -n asya-system -l app.kubernetes.io/name=asya-operator | grep "runtime ConfigMap"
```

Verify namespace exists:
```bash
kubectl get namespace asya
```

### AsyncActor resources not reconciling

Check if operator is watching the correct namespace:
```bash
kubectl get asyncactor -A
kubectl describe asyncactor -n asya <actor-name>
```

Check operator events:
```bash
kubectl get events -n asya --sort-by='.lastTimestamp'
```

### Operator CrashLoopBackOff

Common causes:
1. **Cache not started**: Operator tried to read objects before cache sync - should be fixed in v1.0.0+
2. **RBAC permissions missing**: Verify ClusterRole has required permissions
3. **Runtime ConfigMap errors**: Check if local path is accessible or GitHub repo is public

### Multiple operator versions

**Problem**: Cannot run multiple operator versions in same cluster (CRD conflict)

**Solution**: Use separate clusters for different operator versions:
- `cluster-prod`: Operator v1.2.0
- `cluster-staging`: Operator v1.3.0-rc1

## Development

### Building from source

```bash
# Build operator binary
cd operator
go build -o bin/manager ./cmd/main.go

# Build Docker image
make docker-build IMG=asya-operator:dev

# Load into Kind cluster
kind load docker-image asya-operator:dev
```

### Testing locally with Kind

```bash
# Create Kind cluster
kind create cluster --name asya-dev

# Install CRDs
kubectl apply -f src/asya-operator/config/crd/

# Build and load image
make docker-build IMG=asya-operator:dev
kind load docker-image asya-operator:dev --name asya-dev

# Install operator
helm install asya-operator deploy/helm-charts/asya-operator \
  -n asya-system \
  --create-namespace \
  --set image.tag=dev \
  --set image.pullPolicy=Never
```

## Production Considerations

1. **Use GitHub releases**: Set `runtime.source=github` and pin a specific version
2. **Enable leader election**: Keep `leaderElection.enabled=true` for HA
3. **Set resource limits**: Adjust `resources` based on cluster size and actor count
4. **Configure RBAC**: Review ClusterRole permissions, restrict if possible
5. **Monitor operator logs**: Set up log aggregation (e.g., Loki, CloudWatch)
6. **Backup CRDs**: Keep CRD definitions in version control
7. **Plan CRD upgrades**: Test CRD version migrations in staging first
8. **Separate clusters**: Use different clusters for prod/staging to allow independent operator versions

## License

See main project license.
