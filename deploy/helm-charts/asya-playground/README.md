# Asya Playground Helm Chart

Full demo package showing Asya in action with sample actors, flows, and infrastructure.

## Overview

The `asya-playground` chart is a complete demonstration package that bundles:
- **asya-crossplane** - XRDs and Compositions for AsyncActor resources (sidecar rendered inline)
- **Crew Actors** - System actors (x-sink, x-sump)
- **Gateway** - MCP gateway with PostgreSQL backend
- **Sample Actors** - Hello-world actor for validation and testing
- **Sample Infrastructure** - LocalStack (SQS/S3), RabbitMQ, MinIO for demos
- **Monitoring** - Optional kube-prometheus-stack with pre-configured dashboards

This chart is ideal for:
- Quick demos and evaluations
- Learning Asya concepts
- Local development and testing
- CI/CD pipeline validation

**IMPORTANT**: This is a demo package. For production deployments, install components separately with proper cloud services and configurations.

## Prerequisites

- Kubernetes 1.28+
- Helm 3.12+
- kubectl configured for your cluster

Crossplane and KEDA must be installed separately before this chart. Crossplane
CRDs must be available when the playground chart renders `asya-crossplane` templates.

## Installation

Three steps: install Crossplane, install the playground, then enable actors after
Crossplane providers have registered their CRDs.

### Step 1: Install prerequisites (Crossplane and KEDA)

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace \
  --wait --timeout 120s

helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda \
  --namespace keda --create-namespace \
  --wait --timeout 120s
```

### Step 2: Install infrastructure

```bash
helm repo add asya https://asya.sh/charts
helm repo update asya

helm install asya asya/asya-playground \
  --namespace asya-demo --create-namespace \
  --set global.transport=sqs \
  --set global.storage=s3 \
  --timeout 600s --wait
```

### Step 3: Wait for CRDs, enable actors

```bash
# Wait for Crossplane providers and functions to become healthy
kubectl wait --for=condition=Healthy \
  providers/provider-aws-sqs providers/provider-kubernetes \
  functions/function-go-templating functions/function-patch-and-transform functions/function-auto-ready \
  --timeout=300s
kubectl wait --for=condition=Established xrd/xasyncactors.asya.sh --timeout=120s

# Enable ProviderConfigs, crew actors, and hello actor
helm upgrade asya asya/asya-playground --namespace asya-demo \
  --reuse-values \
  --set asya-crossplane.providerConfigs.install=true \
  --set enableAsyaCrew=true \
  --set helloActor.enabled=true \
  --timeout 300s --wait
```

### RabbitMQ + MinIO

```bash
helm install asya asya/asya-playground \
  --namespace asya-demo --create-namespace \
  --set global.transport=rabbitmq \
  --set global.storage=minio \
  --timeout 600s --wait
```

### Production (External Infrastructure)

Use existing/managed services instead of sample infrastructure:

```bash
# AWS SQS + S3 + RDS PostgreSQL
helm install asya asya/asya-playground \
  --namespace asya-demo --create-namespace \
  --set global.transport=sqs \
  --set global.storage=s3 \
  --set global.profile=production \
  --set sampleTransport.sqsLocalstack.enabled=false \
  --set sampleStorage.s3Localstack.enabled=false \
  --set sampleGatewayDb.postgresql.enabled=false \
  --set asya-crossplane.awsAccountId=YOUR_AWS_ACCOUNT_ID \
  --set asya-crossplane.awsProviderConfig.endpoint.enabled=false \
  --set asya-crew.storage.s3.endpoint="" \
  --set asya-crew.storage.s3.forcePathStyle=false \
  --set asya-gateway.externalDatabase.host=YOUR_RDS_ENDPOINT \
  --set asya-gateway.externalDatabase.password=YOUR_DB_PASSWORD

# Or use a values file (recommended for production)
helm install asya asya/asya-playground \
  --namespace asya-demo --create-namespace \
  -f production-values.yaml
```

**Production values example** (`production-values.yaml`):
```yaml
global:
  transport: sqs
  storage: s3
  profile: production

# Disable all sample infrastructure
sampleTransport:
  sqsLocalstack:
    enabled: false
  rabbitmq:
    enabled: false
sampleStorage:
  s3Localstack:
    enabled: false
  minio:
    enabled: false
sampleGatewayDb:
  postgresql:
    enabled: false

# Configure external AWS services
asya-crossplane:
  awsRegion: us-east-1
  awsAccountId: "123456789012"
  awsProviderConfig:
    name: default
    credentialsSource: InjectedIdentity  # Use IRSA for production
    endpoint:
      enabled: false  # No custom endpoint for real AWS

asya-crew:
  storage:
    s3:
      endpoint: ""  # Empty for AWS S3
      bucket: my-asya-results
      region: us-east-1
      forcePathStyle: false

asya-gateway:
  externalDatabase:
    host: my-db.rds.amazonaws.com
    port: 5432
    database: asya_gateway
    username: asya
    password: "use-k8s-secret-in-real-deployment"
```

## Configuration

### Global Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.transport` | Message transport (sqs, rabbitmq) | `sqs` |
| `global.storage` | Storage backend (s3, minio) | `s3` |
| `global.profile` | Deployment profile (local, production) | `local` |

### Component Toggles

| Parameter | Description | Default |
|-----------|-------------|---------|
| `enableAsyaCrew` | Deploy crew actors | `false` |
| `enableAsyaGateway` | Deploy MCP gateway | `false` |
| `helloActor.enabled` | Deploy test hello-world actor | `false` |

Crew actors and the hello actor default to `false` because they require Crossplane
CRDs to be established first (see two-phase installation above).

### Sample Infrastructure

**WARNING**: Sample infrastructure is for demos only. Use cloud services in production.

Sample infrastructure provides quick-start transport and storage backends for demos and testing:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `sampleTransport.sqsLocalstack.enabled` | Deploy LocalStack for SQS | `true` |
| `sampleTransport.rabbitmq.enabled` | Deploy RabbitMQ | `false` |
| `sampleStorage.s3Localstack.enabled` | Deploy LocalStack for S3 | `true` |
| `sampleStorage.minio.enabled` | Deploy MinIO | `false` |
| `sampleGatewayDb.postgresql.enabled` | Deploy PostgreSQL for gateway | `false` |

**Production Note**: Sample infrastructure components are not suitable for production use. Configure proper cloud services (AWS SQS/S3, hosted RabbitMQ, etc.) instead.

### Namespaces

All components are installed in the release namespace (`--namespace` flag or `default`).

For production deployments with separate namespaces:
- Install Crossplane in `crossplane-system` using its respective chart
- Install this bundle (gateway + actors + infrastructure) in a dedicated namespace

### Hello Actor Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `helloActor.name` | Actor name | `hello` |
| `helloActor.scaling.minReplicaCount` | Minimum replicas | `0` |
| `helloActor.scaling.maxReplicaCount` | Maximum replicas | `10` |
| `helloActor.scaling.queueLength` | Messages per replica | `5` |

See `values.yaml` for complete configuration options.

## Profiles

### Local Profile (`global.profile=local`)

- Deploys sample infrastructure automatically based on transport/storage selection
- SQS transport -> `localstack-sqs` service
- S3 storage -> `s3-localstack` service
- RabbitMQ transport -> `rabbitmq` service
- MinIO storage -> `minio` service
- Uses in-cluster endpoints
- Suitable for Kind, Minikube, or development clusters

### Production Profile (`global.profile=production`)

- No sample infrastructure deployments
- Expects external cloud services (AWS SQS/S3, hosted RabbitMQ, etc.)
- Requires proper IAM roles and credentials
- Disable sample infrastructure:
  - `sampleTransport.sqsLocalstack.enabled=false`
  - `sampleTransport.rabbitmq.enabled=false`
  - `sampleStorage.s3Localstack.enabled=false`
  - `sampleStorage.minio.enabled=false`

## Testing the Installation

After installation, follow the steps in `NOTES.txt` to:

1. Verify all components are running
2. Send a test message to the hello-world actor
3. Watch the actor scale up
4. Check actor logs
5. Test the MCP gateway (if enabled)

Example test command (SQS with LocalStack, namespace `asya-demo`):

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-demo \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack-sqs.asya-demo:4566 \
      --queue-url http://localstack-sqs.asya-demo:4566/000000000000/asya-asya-demo-hello \
      --message-body '{\"id\":\"test-1\",\"route\":{\"prev\":[],\"curr\":\"hello\",\"next\":[]},\"headers\":{},\"payload\":{\"name\":\"World\"}}'
  "
```

## Monitoring and Observability

The chart bundles an optional `kube-prometheus-stack` dependency. Enable it with:

```bash
helm upgrade asya asya/asya-playground --namespace asya-demo \
  --reuse-values \
  --set sampleMonitoring.enabled=true
```

This provides:
- Prometheus for metrics collection
- Grafana with pre-configured dashboards
- Service monitors for Kubernetes components

Access Grafana:
```bash
kubectl port-forward -n asya-demo svc/asya-monitoring-grafana 3000:80
# Default credentials: admin/asya-admin
```

## Uninstallation

```bash
helm uninstall asya -n asya-demo
```

**Note:** PersistentVolumeClaims are not automatically deleted. To remove them:

```bash
kubectl delete pvc -l app=postgresql -n asya-demo
kubectl delete pvc minio-data -n asya-demo
```

## Architecture

```
Prerequisites (install separately):
  - Crossplane operator (crossplane-system namespace)
  - KEDA (keda namespace)

+---------------------------------------------------------+
| Release namespace (e.g., asya-demo)                     |
| - asya-crossplane (XRDs, Compositions, Providers)       |
| - asya-gateway + PostgreSQL (if enabled)                |
| - asya-crew (x-sink, x-sump)                           |
| - hello-world actor                                     |
|                                                         |
| Sample Infrastructure (demo only):                      |
| - localstack-sqs / s3-localstack (if enabled)           |
| - rabbitmq (if enabled)                                 |
| - minio (if enabled)                                    |
+---------------------------------------------------------+
```

**Note**: For production, consider installing components in separate namespaces:
- Crossplane in `crossplane-system`, asya-crossplane in `asya-system`
- Gateway + actors in dedicated namespaces per environment
- Use cloud services instead of sample infrastructure

## Troubleshooting

### Actor not scaling

Verify KEDA is running:
```bash
kubectl get pods -n asya-demo -l app=keda-operator
```

Check ScaledObject:
```bash
kubectl get scaledobject -n asya-demo
kubectl describe scaledobject hello -n asya-demo
```

### Providers not becoming Healthy

```bash
kubectl describe providers provider-aws-sqs
kubectl describe functions function-go-templating
```

Providers pull packages from `xpkg.upbound.io`. On slow connections, increase the `--timeout`.

### AsyncActor stuck in Creating

```bash
kubectl describe asyncactor hello -n asya-demo
kubectl get objects -A   # check provider-kubernetes managed objects
```

Common cause: provider-kubernetes RBAC. Verify the ClusterRoleBinding references
the correct namespace for the `provider-kubernetes` ServiceAccount.

### LocalStack not responding

Check LocalStack SQS health:
```bash
kubectl run curl --rm -i --restart=Never --image=curlimages/curl -- \
  http://localstack-sqs.asya-demo:4566/_localstack/health
```

Check LocalStack S3 health:
```bash
kubectl run curl --rm -i --restart=Never --image=curlimages/curl -- \
  http://s3-localstack.asya-demo:4566/_localstack/health
```

## Dependencies

**Prerequisites** (install separately before this chart):
- `crossplane` (>=1.18.0) - Crossplane operator
- `keda` (>=2.16.0) - Event-driven autoscaler

**Bundled sub-charts**:
- `asya-crossplane` (>=0.1.0) - XRDs, Compositions, Crossplane providers (includes inline sidecar rendering)
- `asya-crew` (>=0.4.0) - System actors
- `asya-gateway` (>=0.4.0) - MCP gateway
- `kube-prometheus-stack` (>=65.0.0) - Optional monitoring stack

Sub-chart dependencies are pulled from `https://asya.sh/charts` (published Helm repository).

## Production Considerations

**IMPORTANT**: This chart is designed for demos and learning. For production deployments, consider:

1. **Install components separately** - Use individual charts (asya-crossplane, asya-gateway, asya-crew) with custom configurations
2. **Use cloud services** - Replace sample infrastructure with AWS SQS/S3, hosted RabbitMQ, managed PostgreSQL
3. **Configure IAM roles** - Set up proper AWS IAM roles for SQS/S3 access
4. **Set resource limits** - Configure appropriate CPU/memory limits for your workload
5. **Enable persistence** - Use persistent storage for PostgreSQL and gateway state
6. **Configure monitoring** - Integrate with production monitoring (Prometheus, Datadog, etc.)
7. **Use Ingress** - Expose gateway externally with proper TLS/authentication
8. **Review security** - Configure RBAC, network policies, secrets management

## Links

- Documentation: https://github.com/deliveryhero/asya
- Quickstart Guide: [Getting Started](../../docs/setup/start-quickstart.md)
- Component Charts: deploy/helm-charts/
