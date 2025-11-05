# Installation

Detailed installation guide for Asya framework.

## Prerequisites

### Required
- **Kubernetes 1.23+** - Any cluster (Minikube, kind, EKS, GKE, AKS)
- **kubectl** - Configured to access your cluster
- **Helm 3.0+** - Package manager for Kubernetes

### Optional
- **KEDA 2.0+** - For autoscaling (can be installed via Helm)
- **Docker** - For building custom images
- **Minikube** - For local development

## Installation Methods

### 1. Automated Full Stack (Minikube)

**Best for**: Local development, testing, learning

Includes complete infrastructure (RabbitMQ, PostgreSQL, MinIO, Prometheus, Grafana, KEDA):

```bash
cd examples/deployment-minikube
./deploy.sh
```

See [Deployment Guide](../guides/deployment.md) for details.

### 2. Manual Installation (Minimal)

**Best for**: Production, existing infrastructure

#### Step 1: Install CRDs

```bash
kubectl apply -f operator/config/crd/
```

Verify:
```bash
kubectl get crd asyncactors.asya.io
```

#### Step 2: Install Operator

```bash
helm install asya-operator deploy/helm-charts/asya-operator \
  --namespace asya-system \
  --create-namespace
```

Verify:
```bash
kubectl get pods -n asya-system
kubectl logs -n asya-system -l app=asya-operator
```

#### Step 3: Install Gateway (Optional)

If you want MCP protocol support:

```bash
helm install asya-gateway deploy/helm-charts/asya-gateway \
  --namespace asya \
  --create-namespace \
  --set postgresql.enabled=true
```

Verify:
```bash
kubectl get pods -n asya
kubectl get svc -n asya asya-gateway
```

#### Step 4: Install KEDA (Optional)

For autoscaling support:

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

helm install keda kedacore/keda \
  --namespace keda \
  --create-namespace
```

Verify:
```bash
kubectl get pods -n keda
```

## Configuration

### Operator Configuration

The operator can be configured via Helm values:

```yaml
# values.yaml
image:
  repository: asya-operator
  tag: latest
  pullPolicy: IfNotPresent

sidecar:
  image:
    repository: asya-sidecar
    tag: latest

resources:
  limits:
    cpu: 500m
    memory: 256Mi
  requests:
    cpu: 100m
    memory: 64Mi
```

Apply:
```bash
helm upgrade asya-operator deploy/helm-charts/asya-operator \
  -n asya-system \
  -f values.yaml
```

### Gateway Configuration

Configure gateway via values or environment:

```yaml
# gateway-values.yaml
database:
  url: "postgresql://user:pass@postgres:5432/asya"

rabbitmq:
  url: "amqp://guest:guest@rabbitmq:5672/"
  exchange: "asya"

postgresql:
  enabled: true
  auth:
    username: asya
    password: changeme
    database: asya
```

## Verification

### Check Operator Status

```bash
# Check operator pod
kubectl get pods -n asya-system

# Check operator logs
kubectl logs -n asya-system -l app=asya-operator -f

# Check CRD
kubectl get crd asyncactors.asya.io
kubectl explain asya.spec
```

### Check Gateway Status

```bash
# Check gateway pod
kubectl get pods -n asya -l app=asya-gateway

# Check gateway logs
kubectl logs -n asya -l app=asya-gateway -f

# Test health endpoint
kubectl port-forward -n asya svc/asya-gateway 8080:8080
curl http://localhost:8080/health
```

### Deploy Test Actor

```bash
# Apply simple example
kubectl apply -f examples/asyas/simple-actor.yaml

# Check actor status
kubectl get asyas
kubectl describe asya simple-actor

# Check created deployment
kubectl get deployment simple-actor
```

## Troubleshooting

### CRD Not Found

```bash
# Reinstall CRD
kubectl apply -f operator/config/crd/

# Verify
kubectl get crd asyncactors.asya.io -o yaml
```

### Operator Not Starting

```bash
# Check logs
kubectl logs -n asya-system -l app=asya-operator

# Check RBAC
kubectl get serviceaccount -n asya-system
kubectl get clusterrole asya-operator
kubectl get clusterrolebinding asya-operator
```

### Gateway Database Issues

```bash
# Check PostgreSQL pod
kubectl get pods -n asya -l app=postgresql

# Check PostgreSQL logs
kubectl logs -n asya -l app=postgresql

# Run database migrations
kubectl exec -n asya deploy/asya-gateway -- sqitch deploy
```

## Uninstallation

### Remove Actors

```bash
# Delete all actors
kubectl delete asyas --all -A
```

### Uninstall Gateway

```bash
helm uninstall asya-gateway -n asya
kubectl delete namespace asya
```

### Uninstall Operator

```bash
helm uninstall asya-operator -n asya-system
kubectl delete namespace asya-system
```

### Remove CRDs

```bash
kubectl delete crd asyncactors.asya.io
```

## Next Steps

- [Core Concepts](concepts.md) - Understanding Asya
- [Deploy Your First Actor](quickstart.md#deploy-your-first-actor)
- [Component Documentation](../components/gateway.md)
