# Asya🎭 Gateway Helm Chart

This Helm chart deploys the Asya🎭 MCP Gateway with PostgreSQL backend.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- PV provisioner support in the underlying infrastructure (for PostgreSQL persistence)

## Installing the Chart

### With bundled PostgreSQL (recommended for development)

```bash
# Update dependencies
helm dependency update deploy/helm-charts/asya-gateway

# Install
helm install asya-gateway deploy/helm-charts/asya-gateway \
  --create-namespace \
  --namespace asya
```

### With external PostgreSQL (recommended for production)

```bash
# Create secret with database credentials
kubectl create secret generic asya-gateway-db-external \
  --from-literal=password='your-secure-password' \
  -n asya

# Install chart with external database
helm install asya-gateway deploy/helm-charts/asya-gateway \
  --create-namespace \
  --namespace asya \
  --set postgresql.enabled=false \
  --set externalDatabase.host=postgres.example.com \
  --set externalDatabase.port=5432 \
  --set externalDatabase.database=asya_gateway \
  --set externalDatabase.username=asya \
  --set externalDatabase.existingSecret=asya-gateway-db-external
```

## Configuration

### Gateway Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of gateway replicas | `1` |
| `image.repository` | Gateway image repository | `asya-gateway` |
| `image.tag` | Gateway image tag | `latest` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `config.port` | Gateway HTTP port | `"8080"` |
| `config.awsRegion` | AWS region for SQS | `"us-east-1"` |
| `config.queueBaseURL` | SQS base URL | `"http://localstack:4566/000000000000"` |

### PostgreSQL Configuration (bundled)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `postgresql.enabled` | Enable bundled PostgreSQL | `true` |
| `postgresql.auth.database` | Database name | `asya_gateway` |
| `postgresql.auth.username` | Database username | `asya` |
| `postgresql.auth.password` | Database password | `asya-password` |
| `postgresql.primary.persistence.enabled` | Enable PostgreSQL persistence | `true` |
| `postgresql.primary.persistence.size` | PostgreSQL PVC size | `8Gi` |

### External Database Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `externalDatabase.host` | External PostgreSQL host | `postgres.example.com` |
| `externalDatabase.port` | External PostgreSQL port | `5432` |
| `externalDatabase.database` | Database name | `asya_gateway` |
| `externalDatabase.username` | Database username | `asya` |
| `externalDatabase.existingSecret` | Secret containing password | `""` |
| `externalDatabase.existingSecretKey` | Key in secret containing password | `password` |

### Database Migration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `migration.enabled` | Enable automatic database migration | `true` |
| `migration.image.repository` | Sqitch image repository | `sqitch/sqitch` |
| `migration.image.tag` | Sqitch image tag | `latest-pg` |
| `migration.backoffLimit` | Migration job backoff limit | `5` |

## Database Schema

The gateway uses two main tables:

- **envelopes**: Stores envelope metadata and current state
- **envelope_updates**: Audit log of all envelope status changes (for SSE streaming)

Migrations are managed with Sqitch and run automatically as a Helm pre-install/pre-upgrade hook.

## Accessing the Gateway

### Port-forward for local development

```bash
kubectl port-forward -n asya svc/asya-gateway 8080:80
```

### Test endpoints

```bash
# Health check
curl http://localhost:8080/health

# MCP JSON-RPC endpoint
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {
        "name": "test-client",
        "version": "1.0.0"
      }
    }
  }'
```

## Upgrading the Chart

```bash
# Update dependencies
helm dependency update deploy/helm-charts/asya-gateway

# Upgrade
helm upgrade asya-gateway deploy/helm-charts/asya-gateway -n asya
```

Database migrations will run automatically before the gateway pods are updated.

## Uninstalling the Chart

```bash
helm uninstall asya-gateway -n asya
```

**WARNING**: This will delete the PostgreSQL database if using bundled PostgreSQL. Ensure you have backups if needed.

## Production Considerations

1. **Use external PostgreSQL**: Set `postgresql.enabled=false` and configure `externalDatabase`
2. **Enable persistence**: For bundled PostgreSQL, ensure `postgresql.primary.persistence.enabled=true`
3. **Set strong passwords**: Change default passwords in production
4. **Configure resource limits**: Adjust `resources` and `postgresql.primary.resources`
5. **Enable ingress**: Configure `ingress.enabled=true` with appropriate TLS settings
6. **Set up backups**: Configure PostgreSQL backups for bundled database
7. **Configure autoscaling**: Enable HPA with `autoscaling.enabled=true`

## Troubleshooting

### Check migration job status

```bash
kubectl get jobs -n asya -l app.kubernetes.io/component=migration
kubectl logs -n asya job/asya-gateway-db-migration
```

### Check gateway logs

```bash
kubectl logs -n asya -l app.kubernetes.io/name=asya-gateway
```

### Connect to database

```bash
# For bundled PostgreSQL
kubectl port-forward -n asya svc/asya-gateway-postgresql 5432:5432

# Connect with psql
PGPASSWORD=asya-password psql -h localhost -p 5432 -U asya -d asya_gateway
```

### Check database tables

```sql
-- List all tables
\dt

-- Check jobs table
SELECT * FROM jobs LIMIT 10;

-- Check job_updates table
SELECT * FROM job_updates LIMIT 10;
```
