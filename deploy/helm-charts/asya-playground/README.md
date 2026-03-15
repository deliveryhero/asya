# Asya Quickstart Helm Chart

Full demo package showing Asya🎭 in action with sample actors, flows, and infrastructure.

## Overview

The `asya-playground` chart is a complete demonstration package that bundles:
- **Crossplane** - XRDs and Compositions for AsyncActor resources (sidecar rendered inline)
- **Crew Actors** - System actors (x-sink, x-sump)
- **Gateway** - MCP gateway with PostgreSQL backend
- **Sample Actors** - Hello-world actor for validation and testing
- **Sample Infrastructure** - LocalStack (SQS/S3), RabbitMQ, MinIO for demos

This chart is ideal for:
- Quick demos and evaluations
- Learning Asya🎭 concepts
- Local development and testing
- CI/CD pipeline validation

**IMPORTANT**: This is a demo package. For production deployments, install components separately with proper cloud services and configurations.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.8+
- kubectl configured for your cluster
- [Crossplane](https://crossplane.io/) installed in the cluster

For production deployments, install components separately with proper cloud services and custom configurations.

## Installation

### Quick Start (SQS + S3 via LocalStack)

```bash
# From Helm repository
helm repo add asya https://asya.sh/charts
helm repo update
helm install asya asya/asya-playground \
  --create-namespace \
  --namespace asya-playground \
  --set global.transport=sqs \
  --set global.storage=s3 \
  --set global.profile=local

# Or from local filesystem
helm install asya deploy/helm-charts/asya-playground/ \
  --create-namespace \
  --namespace asya-playground \
  --set global.transport=sqs \
  --set global.storage=s3 \
  --set global.profile=local
```

### RabbitMQ + MinIO

```bash
helm install asya deploy/helm-charts/asya-playground/ \
  --create-namespace \
  --namespace asya-playground \
  --set global.transport=rabbitmq \
  --set global.storage=minio \
  --set global.profile=local
```

### Production (External Infrastructure)

Use existing/managed services instead of sample infrastructure:

```bash
# AWS SQS + S3 + RDS PostgreSQL
helm install asya deploy/helm-charts/asya-playground/ \
  --create-namespace \
  --namespace asya-playground \
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
helm install asya deploy/helm-charts/asya-playground/ \
  --create-namespace \
  --namespace asya-playground \
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
| `enableAsyaCrew` | Deploy crew actors | `true` |
| `enableAsyaGateway` | Deploy MCP gateway | `true` |
| `helloActor.enabled` | Deploy test hello-world actor | `true` |

### Sample Infrastructure

**WARNING**: Sample infrastructure is for demos only. Use cloud services in production.

Sample infrastructure provides quick-start transport and storage backends for demos and testing:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `sampleTransport.sqsLocalstack.enabled` | Deploy LocalStack for SQS | `true` |
| `sampleTransport.rabbitmq.enabled` | Deploy RabbitMQ | `false` |
| `sampleStorage.s3Localstack.enabled` | Deploy LocalStack for S3 | `true` |
| `sampleStorage.minio.enabled` | Deploy MinIO | `false` |
| `sampleGatewayDb.postgresql.enabled` | Deploy PostgreSQL for gateway | `true` |

**Production Note**: Sample infrastructure components are not suitable for production use. Configure proper cloud services (AWS SQS/S3, hosted RabbitMQ, etc.) instead.

### Namespaces

All components are installed in the release namespace (`--namespace` flag or `default`).

For production deployments with separate namespaces:
- Install Crossplane in `asya-system` using its respective chart
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
- SQS transport → `localstack-sqs` service
- S3 storage → `s3-localstack` service
- RabbitMQ transport → `rabbitmq` service
- MinIO storage → `minio` service
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

Example test command (SQS):

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack-sqs.asya-playground:4566 \
      --queue-url http://localstack-sqs.asya-playground:4566/000000000000/asya-default-hello \
      --message-body '{\"id\":\"test-1\",\"route\":{\"actors\":[\"hello\"],\"current\":0},\"payload\":{\"name\":\"World\"}}'
  "
```

## Monitoring and Observability

For production-grade monitoring, use the `kube-prometheus-stack` Helm chart from the prometheus-community:

```bash
# Add prometheus-community repository
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install kube-prometheus-stack
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace
```

This provides:
- Prometheus for metrics collection
- Grafana with pre-configured dashboards
- Alert Manager for notifications
- Service monitors for Kubernetes components

Access Grafana:
```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
# Default credentials: admin/prom-operator
```

**Note:** Custom Asya🎭 Grafana dashboards will be added in a future release (tracked separately).

## Uninstallation

```bash
helm uninstall asya -n asya-playground
```

**Note:** PersistentVolumeClaims are not automatically deleted. To remove them:

```bash
kubectl delete pvc -l app=postgresql -n asya-playground
kubectl delete pvc minio-data -n asya-playground
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ Release namespace (e.g., default or asya-demo)       │
│ - asya-crossplane (XRDs, Compositions, Providers)    │
│ - asya-gateway + PostgreSQL                          │
│ - asya-crew (x-sink, x-sump)                         │
│ - hello-world actor                                  │
│                                                       │
│ Sample Infrastructure (demo only):                   │
│ - localstack-sqs / s3-localstack (if enabled)        │
│ - rabbitmq (if enabled)                              │
│ - minio (if enabled)                                 │
└─────────────────────────────────────────────────────┘
```

**Note**: For production, consider installing components in separate namespaces:
- Crossplane in `crossplane-system`, asya-crossplane in `asya-system`
- Gateway + actors in dedicated namespaces per environment
- Use cloud services instead of sample infrastructure

## Troubleshooting

### Actor not scaling

Verify KEDA is installed:
```bash
kubectl get pods -n keda
```

Check ScaledObject:
```bash
kubectl get scaledobject -n asya-playground
kubectl describe scaledobject hello -n asya-playground
```

### Gateway connection errors

Check gateway logs:
```bash
kubectl logs -n asya-playground -l app.kubernetes.io/name=asya-gateway
```

Verify PostgreSQL is ready:
```bash
kubectl get pods -l app=postgresql -n asya-playground
```

### LocalStack not responding

Check LocalStack SQS health:
```bash
kubectl run curl --rm -i --restart=Never --image=curlimages/curl -- \
  http://localstack-sqs.asya-playground:4566/_localstack/health
```

Check LocalStack S3 health:
```bash
kubectl run curl --rm -i --restart=Never --image=curlimages/curl -- \
  http://s3-localstack.asya-playground:4566/_localstack/health
```

## Dependencies

This umbrella chart depends on:
- `asya-crossplane` (>=0.1.0) - XRDs, Compositions, Crossplane providers (includes inline sidecar rendering)
- `asya-crew` (>=0.4.0) - System actors
- `asya-gateway` (>=0.4.0) - MCP gateway

Dependencies are pulled from `https://asya.sh/charts` (published Helm repository).

## Load Testing (Future)

Load testing capabilities for stress-testing actor pipelines are tracked in a separate work item and will be added in a future release.

## Production Considerations

**IMPORTANT**: This quickstart chart is designed for demos and learning. For production deployments, consider:

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
- Quickstart Guide: docs/quickstart/README.md
- Component Charts: deploy/helm-charts/
