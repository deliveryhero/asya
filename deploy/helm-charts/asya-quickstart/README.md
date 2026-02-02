# Asya Quickstart Helm Chart

Full demo package showing Asya🎭 in action with sample actors, flows, and infrastructure.

## Overview

The `asya-quickstart` chart is a complete demonstration package that bundles:
- **Operator + CRDs** - Kubernetes operator for AsyncActor resources
- **Crew Actors** - System actors (happy-end, error-end)
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

For production deployments, install components separately with proper cloud services and custom configurations.

## Installation

### Quick Start (SQS + S3 via LocalStack)

```bash
# From Helm repository
helm repo add asya https://asya.sh/charts
helm repo update
helm install asya asya/asya-quickstart \
  --create-namespace \
  --namespace default \
  --set global.transport=sqs \
  --set global.storage=s3 \
  --set global.profile=local

# Or from local filesystem
helm install asya deploy/helm-charts/asya-quickstart/ \
  --create-namespace \
  --namespace default \
  --set global.transport=sqs \
  --set global.storage=s3 \
  --set global.profile=local
```

### RabbitMQ + MinIO

```bash
helm install asya deploy/helm-charts/asya-quickstart/ \
  --create-namespace \
  --namespace default \
  --set global.transport=rabbitmq \
  --set global.storage=minio \
  --set global.profile=local
```

### Production (AWS SQS + S3)

```bash
helm install asya deploy/helm-charts/asya-quickstart/ \
  --create-namespace \
  --namespace default \
  --set global.transport=sqs \
  --set global.storage=s3 \
  --set global.profile=production \
  --set sampleTransports.sqsLocalstack.enabled=false \
  --set sampleStorages.s3Localstack.enabled=false \
  --set asya-operator.transports.sqs.config.accountId=YOUR_AWS_ACCOUNT_ID \
  --set asya-operator.transports.sqs.config.endpoint=""
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
| `operator.enabled` | Deploy operator | `true` |
| `crew.enabled` | Deploy crew actors | `true` |
| `gateway.enabled` | Deploy MCP gateway | `true` |
| `helloActor.enabled` | Deploy test hello-world actor | `true` |

### Sample Infrastructure

**WARNING**: Sample infrastructure is for demos only. Use cloud services in production.

Sample infrastructure provides quick-start transport and storage backends for demos and testing:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `sampleTransports.sqsLocalstack.enabled` | Deploy LocalStack for SQS | `true` |
| `sampleTransports.rabbitmq.enabled` | Deploy RabbitMQ | `false` |
| `sampleStorages.s3Localstack.enabled` | Deploy LocalStack for S3 | `true` |
| `sampleStorages.minio.enabled` | Deploy MinIO | `false` |
| `postgresql.enabled` | Deploy PostgreSQL for gateway | `true` |

**Production Note**: Sample infrastructure components are not suitable for production use. Configure proper cloud services (AWS SQS/S3, hosted RabbitMQ, etc.) instead.

### Namespaces

All components are installed in the release namespace (`--namespace` flag or `default`).

For production deployments with separate namespaces:
- Install operator separately in `asya-system` using the `asya-operator` chart
- Install this bundle (gateway + actors + infrastructure) in a dedicated namespace

### Hello Actor Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `helloActor.name` | Actor name | `hello` |
| `helloActor.scaling.minReplicas` | Minimum replicas | `0` |
| `helloActor.scaling.maxReplicas` | Maximum replicas | `10` |
| `helloActor.scaling.queueLength` | Messages per replica | `5` |

See `values.yaml` for complete configuration options.

## Profiles

### Local Profile (`global.profile=local`)

- Deploys sample infrastructure automatically based on transport/storage selection
- SQS transport → `localstack-sqs` service
- S3 storage → `localstack-s3` service
- RabbitMQ transport → `rabbitmq` service
- MinIO storage → `minio` service
- Uses in-cluster endpoints
- Suitable for Kind, Minikube, or development clusters

### Production Profile (`global.profile=production`)

- No sample infrastructure deployments
- Expects external cloud services (AWS SQS/S3, hosted RabbitMQ, etc.)
- Requires proper IAM roles and credentials
- Disable sample infrastructure:
  - `sampleTransports.sqsLocalstack.enabled=false`
  - `sampleTransports.rabbitmq.enabled=false`
  - `sampleStorages.s3Localstack.enabled=false`
  - `sampleStorages.minio.enabled=false`

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
      --endpoint-url=http://localstack-sqs.default:4566 \
      --queue-url http://localstack-sqs.default:4566/000000000000/asya-default-hello \
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
helm uninstall asya -n default
```

**Note:** PersistentVolumeClaims are not automatically deleted. To remove them:

```bash
kubectl delete pvc -l app=postgresql -n default
kubectl delete pvc minio-data -n default
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ Release namespace (e.g., default or asya-demo)       │
│ - asya-operator                                      │
│ - asya-gateway + PostgreSQL                          │
│ - asya-crew (happy-end, error-end)                   │
│ - hello-world actor                                  │
│                                                       │
│ Sample Infrastructure (demo only):                   │
│ - localstack-sqs / localstack-s3 (if enabled)        │
│ - rabbitmq (if enabled)                              │
│ - minio (if enabled)                                 │
└─────────────────────────────────────────────────────┘
```

**Note**: For production, consider installing components in separate namespaces:
- Operator in `asya-system`
- Gateway + actors in dedicated namespaces per environment
- Use cloud services instead of sample infrastructure

## Troubleshooting

### Pods not starting

Check operator logs:
```bash
kubectl logs -n asya-system -l app.kubernetes.io/name=asya-operator
```

### Actor not scaling

Verify KEDA is installed:
```bash
kubectl get pods -n keda
```

Check ScaledObject:
```bash
kubectl get scaledobject -n default
kubectl describe scaledobject hello -n default
```

### Gateway connection errors

Check gateway logs:
```bash
kubectl logs -n default -l app.kubernetes.io/name=asya-gateway
```

Verify PostgreSQL is ready:
```bash
kubectl get pods -l app=postgresql -n default
```

### LocalStack not responding

Check LocalStack SQS health:
```bash
kubectl run curl --rm -i --restart=Never --image=curlimages/curl -- \
  http://localstack-sqs.default:4566/_localstack/health
```

Check LocalStack S3 health:
```bash
kubectl run curl --rm -i --restart=Never --image=curlimages/curl -- \
  http://localstack-s3.default:4566/_localstack/health
```

## Dependencies

This umbrella chart depends on:
- `asya-operator` (>=0.1.0)
- `asya-crew` (>=0.4.0)
- `asya-gateway` (>=0.1.0)

Dependencies are pulled from `file://../{chart-name}` (local filesystem).

## Load Testing (Future)

Load testing capabilities for stress-testing actor pipelines are tracked in a separate work item and will be added in a future release.

## Production Considerations

**IMPORTANT**: This quickstart chart is designed for demos and learning. For production deployments, consider:

1. **Install components separately** - Use individual charts (asya-operator, asya-gateway, asya-crew) with custom configurations
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
