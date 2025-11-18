# Transports

Asya supports pluggable message queue transports for actor communication.

## Overview

Transport layer is abstracted - sidecar implements transport interface, allowing different queue backends.

## Supported Transports

- **[SQS](sqs.md)**: AWS-managed queue service
- **[RabbitMQ](rabbitmq.md)**: Self-hosted open-source message broker

## Planned Transports

- **Kafka**: High-throughput distributed streaming
- **NATS**: Cloud-native messaging system
- **Google Pub/Sub**: GCP-managed messaging service

See [KEDA scalers](https://keda.sh/docs/2.18/scalers/) for potential integration targets.

## Transport Configuration

Transports configured at operator installation time in `deploy/helm-charts/asya-operator/values.yaml`:

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
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
      endpoint: ""  # Optional, for LocalStack or custom SQS endpoints
      visibilityTimeout: 300  # Optional, seconds, defaults to 300
      waitTimeSeconds: 20  # Optional, seconds, defaults to 20
      queues:
        autoCreate: true  # Optional, defaults to true
        forceRecreate: false  # Optional, defaults to false
        dlq:
          enabled: true  # Optional
          maxRetryCount: 3  # Optional, defaults to 3
          retentionDays: 14  # Optional, defaults to 14
      tags:  # Optional, tags for created queues
        Environment: production
        Team: ml-platform
```

AsyncActors reference transport by name:
```yaml
spec:
  transport: sqs  # or rabbitmq
```

## Transport Interface

Sidecar implements (`src/asya-sidecar/internal/transport/transport.go`):

- `Receive(ctx, queueName)`: Receive single message from queue (blocking with long polling)
- `Send(ctx, queueName, body)`: Send message body to queue
- `Ack(ctx, message)`: Acknowledge successful processing
- `Nack(ctx, message)`: Negative acknowledge (requeue or move to DLQ)

## Queue Management

Queues automatically created by operator when AsyncActor reconciled.

**Queue naming**: `asya-{actor_name}`

**Lifecycle**:

- Created when AsyncActor created
- Deleted when AsyncActor deleted
- Preserved when AsyncActor updated

## Adding New Transport

1. Implement transport interface in `src/asya-sidecar/internal/transport/`
2. Add transport configuration to operator
3. Add KEDA scaler configuration
4. Update documentation

See [`src/asya-sidecar/internal/transport/`](https://github.com/deliveryhero/asya/tree/main/src/asya-sidecar/internal/transport) for implementation examples.
