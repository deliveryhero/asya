# RabbitMQ Transport

Self-hosted open-source message broker.

## Configuration

**Operator config**:
```yaml
transports:
  rabbitmq:
    enabled: true
    type: rabbitmq
    config:
      host: rabbitmq.default.svc.cluster.local
      port: 5672
      username: guest
      passwordSecretRef:
        name: rabbitmq-secret
        key: password
```

**AsyncActor reference**:
```yaml
spec:
  transport: rabbitmq
```

## Queue Creation

Operator creates RabbitMQ queues via management API:

**Queue name**: `asya-{actor-name}`

**Example**: Actor `text-processor` → Queue `asya-text-processor`

**Properties**:
- Durable: `true`
- Auto-delete: `false`
- Arguments: DLQ configuration

## Authentication

**Password stored in Kubernetes Secret**:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rabbitmq-secret
type: Opaque
data:
  password: <base64-encoded-password>
```

**Sidecar reads** secret via operator injection.

## KEDA Scaler

```yaml
triggers:
- type: rabbitmq
  metadata:
    host: amqp://guest:password@rabbitmq:5672
    queueName: asya-actor
    queueLength: "5"
```

## DLQ Configuration

Queues configured with dead-letter exchange:

**DLX**: `asya-dlx`

**DLQ**: `asya-{actor-name}-dlq`

Messages move to DLQ after max retries.

## Best Practices

- Use TLS for production (`amqps://`)
- Set appropriate prefetch count
- Monitor RabbitMQ metrics (queue depth, consumer count)
- Use RabbitMQ clustering for HA

## Deployment

**RabbitMQ deployed separately**:
```bash
# Example: Official RabbitMQ manifest
kubectl apply -f testing/e2e/manifests/rabbitmq.yaml
```

**See**: [../../install/local-kind.md](../../install/local-kind.md) for local setup.

## Cost Considerations

- Self-hosted: Pay for compute only
- No per-request charges
- Requires maintenance
- Scales with cluster size

**Trade-off**: Lower costs, higher operational complexity vs SQS.
