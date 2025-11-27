# RabbitMQ Transport

Self-hosted open-source message broker.

**Features**:

- Topic exchange routing
- Automatic queue declaration and binding
- Prefetch control for load management
- Durable queues and persistent messages

**Configuration**:

- AMQP connection URL
- Exchange name
- Prefetch count

## Configuration

**Operator config** (`deploy/helm-charts/asya-operator/values.yaml`):
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
      exchange: asya  # Optional, defaults to "asya"
      queues:
        autoCreate: true  # Optional, defaults to true
        forceRecreate: false  # Optional, defaults to false
        dlq:
          enabled: true  # Optional
          maxRetryCount: 3  # Optional, defaults to 3
```

**AsyncActor reference**:
```yaml
spec:
  transport: rabbitmq
```

**Sidecar environment variables** (injected by operator):

- `ASYA_TRANSPORT=rabbitmq`
- `ASYA_RABBITMQ_HOST` → from `config.host`
- `ASYA_RABBITMQ_PORT` → from `config.port` (default: 5672)
- `ASYA_RABBITMQ_USERNAME` → from `config.username` (default: guest)
- `ASYA_RABBITMQ_PASSWORD` → from `config.passwordSecretRef` (secret reference)
- `ASYA_RABBITMQ_EXCHANGE` → from `config.exchange` (optional, default: asya)
- `ASYA_QUEUE_AUTO_CREATE` → from `config.queues.autoCreate`

**Sidecar builds connection URL**:
```
amqp://{username}:{password}@{host}:{port}/
```

## Queue Creation

**Two modes**:

1. **Operator creates queues** (default): Operator uses RabbitMQ Management API to create durable queues when AsyncActor is reconciled

2. **Sidecar auto-creates queues**: If `queues.autoCreate: true`, sidecar declares queues on first use

**Queue name**: `asya-{actor_name}`

**Example**: Actor `text-processor` → Queue `asya-text-processor`

**Queue properties**:

- Durable: `true`
- Auto-delete: `false`
- Exclusive: `false`

**Exchange**: Topic exchange named `asya` (or configured value)

**Routing key**: Actor name without `asya-` prefix (e.g., `text-processor`)

**Binding**: Queue bound to exchange with routing key

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

**Operator injects** secret reference into sidecar environment via `SecretKeyRef`.

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

When `queues.dlq.enabled: true`, queues are configured with dead-letter exchange:

**DLX**: `asya-dlx` (dead-letter exchange)

**DLQ**: `asya-{actor_name}-dlq` (dead-letter queue per actor)

**Max retries**: Configured via `queues.dlq.maxRetryCount` (default: 3)

**Behavior**: Messages move to DLQ after being nacked `maxRetryCount` times.

## Implementation Details

**Prefetch count**: Sidecar sets QoS prefetch to 1 (configurable via `ASYA_RABBITMQ_PREFETCH`)

**Consumer model**: Long-lived consumer per queue, reused across messages

**Reconnection**: Automatic reconnection with exponential backoff (5 retries, initial 1s backoff)

**Channel recovery**: Automatic channel recreation on closure with QoS and exchange re-declaration

**Exchange type**: Topic exchange for flexible routing patterns

**Message delivery**: Persistent delivery mode for message durability

**Nack behavior**: `Nack()` requeues message (unless DLQ threshold exceeded)

## Best Practices

- Use TLS for production (`amqps://`)
- Set appropriate prefetch count for workload (default: 1)
- Monitor RabbitMQ metrics (queue depth, consumer count, unacknowledged messages)
- Use RabbitMQ clustering for HA
- Enable DLQ for production workloads
- Monitor Management API port 15672 for queue metrics

## Deployment

**RabbitMQ deployed separately** (example for local Kind using the maintained Helm chart):
```bash
helm upgrade --install asya-rabbitmq testing/e2e/charts/rabbitmq \
  --namespace asya-e2e --create-namespace

kubectl wait --for=condition=ready pod -l app=rabbitmq \
  -n asya-e2e --timeout=300s
```

**See**: [../../install/local-kind.md](../../install/local-kind.md) for full local setup.

## Cost Considerations

- Self-hosted: Pay for compute only
- No per-request charges
- Requires maintenance
- Scales with cluster size

**Trade-off**: Lower costs, higher operational complexity vs SQS.
