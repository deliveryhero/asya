# Deployment Guide

Guide for deploying Asya framework in various environments.

> 📄 **Examples**: [`examples/`](../../examples/)
> 📖 **Examples README**: [`examples/README.md`](../../examples/README.md)

## Deployment Options

### Option 1: Full OSS Stack (Minikube)

**Best for**: Local development, testing, learning

Complete deployment with all infrastructure:

```bash
cd examples/deployment-minikube
./deploy.sh
```

**Includes:**
- RabbitMQ (message queue)
- PostgreSQL (job storage)
- MinIO (object storage)
- Prometheus + Grafana (monitoring)
- KEDA (autoscaling)
- Asya Operator + Gateway
- Example actors

**Deployment time**: ~5-10 minutes

See [`examples/deployment-minikube/README.md`](../../examples/deployment-minikube/README.md) for details.

### Option 2: Minimal Framework

**Best for**: Production, existing infrastructure

Install just the framework components:

```bash
cd examples/deployment-minimal

# Using helmfile
helmfile sync

# Or manual
kubectl apply -f ../operator/config/crd/
helm install asya-operator ../../deploy/helm-charts/asya-operator -n asya-system --create-namespace
helm install keda kedacore/keda -n keda --create-namespace
```

**Includes:**
- KEDA (autoscaling)
- Asya Operator
- Asya Gateway (optional)

**Prerequisites**: Bring your own RabbitMQ, PostgreSQL, monitoring

See [`examples/deployment-minimal/README.md`](../../examples/deployment-minimal/README.md) for details.

## Infrastructure Requirements

### Required Components

**RabbitMQ:**
```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install rabbitmq bitnami/rabbitmq -n asya --create-namespace \
  --set auth.username=admin \
  --set auth.password=changeme
```

**KEDA:**
```bash
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda -n keda --create-namespace
```

### Optional Components

**PostgreSQL** (for Gateway):
```bash
helm install postgresql bitnami/postgresql -n asya \
  --set auth.username=asya \
  --set auth.password=changeme \
  --set auth.database=asya
```

**Prometheus + Grafana** (for monitoring):
```bash
helm install prometheus prometheus-community/prometheus -n monitoring --create-namespace
helm install grafana grafana/grafana -n monitoring
```

## Deployment Strategies

### Strategy 1: Infrastructure First

1. **Deploy infrastructure**:
   ```bash
   # RabbitMQ
   helm install rabbitmq bitnami/rabbitmq -n asya --create-namespace

   # PostgreSQL
   helm install postgresql bitnami/postgresql -n asya

   # KEDA
   helm install keda kedacore/keda -n keda --create-namespace
   ```

2. **Deploy framework**:
   ```bash
   kubectl apply -f operator/config/crd/
   helm install asya-operator deploy/helm-charts/asya-operator -n asya-system --create-namespace
   helm install asya-gateway deploy/helm-charts/asya-gateway -n asya
   ```

3. **Deploy actors**:
   ```bash
   kubectl apply -f examples/asyas/simple-actor.yaml
   ```

### Strategy 2: All-in-One (Helmfile)

```bash
cd examples/deployment-minikube
helmfile sync
```

Helmfile manages dependencies and ordering automatically.

## Production Deployment

### Namespace Strategy

```
asya-system     → Operator
asya            → Gateway, infrastructure
<your-ns>       → Your actors
monitoring      → Prometheus, Grafana
keda            → KEDA
```

### Resource Limits

**Operator:**
```yaml
resources:
  limits:
    cpu: 500m
    memory: 256Mi
  requests:
    cpu: 100m
    memory: 64Mi
```

**Gateway:**
```yaml
resources:
  limits:
    cpu: 1000m
    memory: 512Mi
  requests:
    cpu: 200m
    memory: 128Mi
```

**Sidecar** (per actor):
```yaml
sidecar:
  resources:
    limits:
      cpu: 500m
      memory: 256Mi
    requests:
      cpu: 100m
      memory: 64Mi
```

### High Availability

**Operator:**
- Single instance (leader election can be added)
- StatefulSet for persistence

**Gateway:**
- Multiple replicas (stateless)
- LoadBalancer service
- PostgreSQL for persistence

**Actors:**
- Horizontal scaling via KEDA
- StatefulSet for stateful actors

**Infrastructure:**
- RabbitMQ cluster mode
- PostgreSQL HA (managed service recommended)
- Prometheus HA with remote storage

### Security

**Secrets:**
```bash
# RabbitMQ credentials
kubectl create secret generic rabbitmq-secret \
  -n asya \
  --from-literal=password=<strong-password>

# PostgreSQL credentials
kubectl create secret generic postgresql-secret \
  -n asya \
  --from-literal=password=<strong-password>
```

**Network Policies:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: asya-actor-policy
  namespace: asya
spec:
  podSelector:
    matchLabels:
      app: asya-actor
  policyTypes:
  - Ingress
  - Egress
  ingress: []
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: rabbitmq
    ports:
    - protocol: TCP
      port: 5672
```

**RBAC:**
- Minimal ServiceAccount permissions
- Operator needs cluster-wide CRD access
- Actors need namespace-scoped access only

## Cloud Provider Specifics

### AWS (EKS)

**RabbitMQ:**
- Amazon MQ for RabbitMQ (managed)
- Self-hosted on EKS

**PostgreSQL:**
- Amazon RDS for PostgreSQL (recommended)

**Storage:**
- Amazon S3 (via MinIO gateway or native)

**Autoscaling:**
- KEDA with SQS scaler (if using SQS)
- Cluster Autoscaler for node scaling

### GCP (GKE)

**RabbitMQ:**
- CloudAMQP (managed)
- Self-hosted on GKE

**PostgreSQL:**
- Cloud SQL for PostgreSQL (recommended)

**Storage:**
- Google Cloud Storage

### Azure (AKS)

**RabbitMQ:**
- CloudAMQP (managed)
- Self-hosted on AKS

**PostgreSQL:**
- Azure Database for PostgreSQL (recommended)

**Storage:**
- Azure Blob Storage

## Monitoring Setup

### Prometheus

```bash
helm install prometheus prometheus-community/prometheus -n monitoring --create-namespace
```

Configure scraping:
```yaml
extraScrapeConfigs: |
  - job_name: 'asya-actors'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
```

### Grafana

```bash
helm install grafana grafana/grafana -n monitoring
```

Access:
```bash
./scripts/port-forward-grafana.sh
```

Import dashboards for:
- Actor performance
- Queue depths
- Error rates
- Scaling behavior

## Verification

### Check Operator

```bash
kubectl get pods -n asya-system
kubectl logs -n asya-system -l app=asya-operator
kubectl get crd asyncactors.asya.io
```

### Check Gateway

```bash
kubectl get pods -n asya -l app=asya-gateway
kubectl logs -n asya -l app=asya-gateway

# Test health endpoint
kubectl port-forward -n asya svc/asya-gateway 8080:8080
curl http://localhost:8080/health
```

### Check Infrastructure

```bash
# RabbitMQ
kubectl get pods -n asya -l app=rabbitmq
kubectl port-forward -n asya svc/rabbitmq 15672:15672
# Open http://localhost:15672

# PostgreSQL
kubectl get pods -n asya -l app=postgresql
kubectl exec -n asya deploy/postgresql -- psql -U asya -c '\l'

# KEDA
kubectl get pods -n keda
```

### Deploy Test Actor

```bash
kubectl apply -f examples/asyas/simple-actor.yaml
kubectl get asyas
kubectl describe asya simple-actor
kubectl get deployment simple-actor
```

## Cleanup

### Remove Actors

```bash
kubectl delete asyas --all -A
```

### Remove Framework

```bash
helm uninstall asya-gateway -n asya
helm uninstall asya-operator -n asya-system
kubectl delete crd asyncactors.asya.io
```

### Remove Infrastructure

```bash
helm uninstall rabbitmq -n asya
helm uninstall postgresql -n asya
helm uninstall keda -n keda
helm uninstall prometheus -n monitoring
helm uninstall grafana -n monitoring
```

### Remove Namespaces

```bash
kubectl delete namespace asya asya-system keda monitoring
```

## Next Steps

- [Testing Guide](testing.md) - Test your deployment
- [Development Guide](development.md) - Local development
- [Building Guide](building.md) - Build custom images
