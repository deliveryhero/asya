# Deployment Examples

Reference deployments for various environments.

> **Examples**: [`examples/`](../../examples/)
> **Examples README**: [`examples/README.md`](../../examples/README.md)

## Minimal Deployment

Minimal framework deployment for any Kubernetes cluster.

**Location:** [`examples/deployment-minimal/`](../../examples/deployment-minimal/)

**Includes:**
- KEDA (autoscaling)
- Asya🎭 Operator
- Asya🎭 Gateway (optional)

**Prerequisites:**
- Existing RabbitMQ
- Existing PostgreSQL (for Gateway)

**Deploy:**
```bash
cd examples/deployment-minimal
helmfile sync
```

**See:** [`examples/deployment-minimal/README.md`](../../examples/deployment-minimal/README.md)

## Minikube Deployment

Complete OSS stack for local development and testing.

**Location:** [`examples/deployment-minikube/`](../../examples/deployment-minikube/)

**Includes:**
- RabbitMQ (message queue)
- PostgreSQL (envelope storage)
- MinIO (object storage)
- Prometheus + Grafana (monitoring)
- KEDA (autoscaling)
- Asya🎭 Operator + Gateway
- Example actors

**Deploy:**
```bash
cd examples/deployment-minikube
./deploy.sh
./test-e2e.sh
```

**Services:**
```bash
# Grafana
../scripts/port-forward-grafana.sh

# RabbitMQ Management
kubectl port-forward -n asya svc/rabbitmq 15672:15672

# Asya🎭 Gateway
kubectl port-forward -n asya svc/asya-gateway 8080:8080
```

**See:** [`examples/deployment-minikube/README.md`](../../examples/deployment-minikube/README.md)

## Production Deployment Pattern

### AWS EKS

```yaml
# Infrastructure (managed services)
# - Amazon MQ for RabbitMQ
# - Amazon RDS for PostgreSQL
# - Amazon S3 for storage

# Framework deployment
---
apiVersion: v1
kind: Namespace
metadata:
  name: asya-system
---
apiVersion: v1
kind: Namespace
metadata:
  name: asya
---
# Install CRDs
kubectl apply -f src/asya-operator/config/crd/

# Operator via Helm
helm install asya-operator deploy/helm-charts/asya-operator \
  -n asya-system \
  --set image.repository=012345678901.dkr.ecr.us-east-1.amazonaws.com/asya-operator \
  --set image.tag=v1.0.0

# Gateway via Helm
helm install asya-gateway deploy/helm-charts/asya-gateway \
  -n asya \
  --set image.repository=012345678901.dkr.ecr.us-east-1.amazonaws.com/asya-gateway \
  --set image.tag=v1.0.0 \
  --set database.url=postgresql://user:pass@my-rds.us-east-1.rds.amazonaws.com:5432/asya \
  --set rabbitmq.url=amqps://user:pass@b-xxx.mq.us-east-1.amazonaws.com:5671 \
  --set postgresql.enabled=false

# KEDA
helm install keda kedacore/keda -n keda --create-namespace
```

**Actors:**
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: production-actor
  namespace: production
spec:
  # Actor name is automatically used as the queue name
  transport: rabbitmq

  sidecar:
    image: 012345678901.dkr.ecr.us-east-1.amazonaws.com/asya-sidecar:v1.0.0
    imagePullPolicy: Always

  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 100
    queueLength: 5

  workload:
    type: Deployment
    template:
      spec:
        serviceAccountName: production-actor-sa
        containers:
        - name: asya-runtime
          image: 012345678901.dkr.ecr.us-east-1.amazonaws.com/my-actor:v2.0.0
          resources:
            limits:
              cpu: 2000m
              memory: 4Gi
            requests:
              cpu: 1000m
              memory: 2Gi
```

### GCP GKE

```yaml
# Infrastructure (managed services)
# - CloudAMQP for RabbitMQ
# - Cloud SQL for PostgreSQL
# - Cloud Storage for objects

# Similar to EKS, adjust:
# - Image repositories (GCR/Artifact Registry)
# - Service endpoints
# - IAM/Workload Identity
```

### Azure AKS

```yaml
# Infrastructure (managed services)
# - CloudAMQP for RabbitMQ
# - Azure Database for PostgreSQL
# - Azure Blob Storage

# Similar to EKS, adjust:
# - Image repositories (ACR)
# - Service endpoints
# - Managed identities
```

## Multi-Tenant Deployment

```yaml
# Namespace per tenant
---
apiVersion: v1
kind: Namespace
metadata:
  name: tenant-a
---
apiVersion: v1
kind: Namespace
metadata:
  name: tenant-b
---
# Shared operator (cluster-scoped)
helm install asya-operator deploy/helm-charts/asya-operator -n asya-system

# Tenant A actors
---
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: tenant-a-actor
  namespace: tenant-a
spec:
  # Actor name is automatically used as the queue name
  transport: rabbitmq
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: tenant-a-app:latest

# Tenant B actors
---
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: tenant-b-actor
  namespace: tenant-b
spec:
  # Actor name is automatically used as the queue name
  transport: rabbitmq
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: tenant-b-app:latest
```

## High Availability Deployment

```yaml
# HA Operator (future: leader election)
helm install asya-operator deploy/helm-charts/asya-operator \
  -n asya-system \
  --set replicaCount=1

# HA Gateway
helm install asya-gateway deploy/helm-charts/asya-gateway \
  -n asya \
  --set replicaCount=3 \
  --set database.url=postgresql://...rds... \
  --set service.type=LoadBalancer

# HA RabbitMQ (cluster mode)
helm install rabbitmq bitnami/rabbitmq \
  -n infrastructure \
  --set replicaCount=3 \
  --set clustering.enabled=true

# HA PostgreSQL (managed service recommended)
# Use Amazon RDS, Cloud SQL, or Azure Database

# Actors with HA considerations
---
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: ha-actor
spec:
  scaling:
    enabled: true
    minReplicas: 2  # Always keep at least 2 running
    maxReplicas: 50

  workload:
    template:
      spec:
        affinity:
          podAntiAffinity:
            preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: ha-actor
                topologyKey: kubernetes.io/hostname
        containers:
        - name: asya-runtime
          image: my-app:latest
```

## Testing Deployments

### Automated Tests

```bash
# Run all deployment tests
cd examples
./run-all-tests.sh

# Test specific deployment
cd examples/deployment-minikube
./test-e2e.sh
```

### Manual Verification

```bash
# Check operator
kubectl get pods -n asya-system
kubectl logs -n asya-system -l app=asya-operator

# Check gateway
kubectl get pods -n asya -l app=asya-gateway
curl http://<gateway-ip>:8080/health

# Check actors
kubectl get asyas -A
kubectl describe asya my-actor

# Check infrastructure
kubectl get pods -n infrastructure
```

## Next Steps

- [Actor Examples](actors.md) - Actor configurations
- [Deployment Guide](../guides/deploy.md) - Deployment strategies
- [Testing Guide](../guides/testing.md) - Test deployments
