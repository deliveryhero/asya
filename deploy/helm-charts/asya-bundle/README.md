# Asya Bundle Helm Chart

Umbrella Helm chart for quick Asya🎭 installation with all components.

## Overview

The `asya-bundle` chart simplifies Asya🎭 deployment by bundling:
- **Operator + CRDs** - Kubernetes operator for AsyncActor resources
- **Crew Actors** - System actors (happy-end, error-end)
- **Gateway** - MCP gateway with PostgreSQL backend
- **Test Actor** - Hello-world actor for validation
- **Infrastructure** - Optional LocalStack, RabbitMQ, MinIO, PostgreSQL for local testing

This chart is ideal for:
- Quick demos and evaluations
- Local development environments
- Testing and CI/CD pipelines

## Prerequisites

- Kubernetes 1.24+
- Helm 3.8+
- kubectl configured for your cluster

For production deployments, consider installing components separately with custom configurations.

## Installation

### Quick Start (SQS + S3 via LocalStack)

```bash
helm install asya deploy/helm-charts/asya-bundle/ \
  --create-namespace \
  --namespace default \
  --set global.transport=sqs \
  --set global.storage=s3 \
  --set global.profile=local
```

### RabbitMQ + MinIO

```bash
helm install asya deploy/helm-charts/asya-bundle/ \
  --create-namespace \
  --namespace default \
  --set global.transport=rabbitmq \
  --set global.storage=minio \
  --set global.profile=local
```

### Production (AWS SQS + S3)

```bash
helm install asya deploy/helm-charts/asya-bundle/ \
  --create-namespace \
  --namespace default \
  --set global.transport=sqs \
  --set global.storage=s3 \
  --set global.profile=production \
  --set localstack.enabled=false \
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

### Infrastructure Components

| Parameter | Description | Default |
|-----------|-------------|---------|
| `localstack.enabled` | Deploy LocalStack (SQS + S3) | `true` |
| `rabbitmq.enabled` | Deploy RabbitMQ | `false` |
| `minio.enabled` | Deploy MinIO | `false` |
| `postgresql.enabled` | Deploy PostgreSQL for gateway | `true` |
| `monitoring.enabled` | Deploy Prometheus + Grafana | `false` |

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

- Deploys LocalStack for SQS/S3 (when `global.transport=sqs` or `global.storage=s3`)
- Deploys RabbitMQ (when `global.transport=rabbitmq`)
- Deploys MinIO (when `global.storage=minio`)
- Uses in-cluster endpoints
- Suitable for Kind, Minikube, or development clusters

### Production Profile (`global.profile=production`)

- No infrastructure deployments
- Expects external cloud services (AWS SQS/S3, etc.)
- Requires proper IAM roles and credentials
- Set `localstack.enabled=false`, `rabbitmq.enabled=false`, etc.

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
      --endpoint-url=http://localstack.default:4566 \
      --queue-url http://localstack.default:4566/000000000000/asya-default-hello \
      --message-body '{\"id\":\"test-1\",\"route\":{\"actors\":[\"hello\"],\"current\":0},\"payload\":{\"name\":\"World\"}}'
  "
```

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
│ - localstack / rabbitmq / minio (if enabled)         │
│ - prometheus / grafana (if monitoring.enabled)       │
└─────────────────────────────────────────────────────┘
```

**Note**: For production, consider installing components in separate namespaces:
- Operator in `asya-system`
- Gateway + actors in dedicated namespaces per environment

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

Check LocalStack health:
```bash
kubectl run curl --rm -i --restart=Never --image=curlimages/curl -- \
  http://localstack.default:4566/_localstack/health
```

## Dependencies

This umbrella chart depends on:
- `asya-operator` (>=0.1.0)
- `asya-crew` (>=0.4.0)
- `asya-gateway` (>=0.1.0)

Dependencies are pulled from `file://../{chart-name}` (local filesystem).

## Production Considerations

For production deployments, consider:

1. **Install components separately** with custom configurations
2. **Use external databases** instead of bundled PostgreSQL
3. **Configure IAM roles** for AWS SQS/S3 access
4. **Set resource limits** appropriate for your workload
5. **Enable persistence** for PostgreSQL and gateway state
6. **Configure monitoring** with Prometheus and Grafana
7. **Use Ingress** to expose gateway externally
8. **Review security** settings (RBAC, network policies)

## Links

- Documentation: https://github.com/deliveryhero/asya
- Quickstart Guide: docs/quickstart/README.md
- Component Charts: deploy/helm-charts/
