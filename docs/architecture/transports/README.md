# Transports

Asya supports pluggable message queue transports for actor communication.

## Overview

Transport layer is abstracted—sidecar implements transport interface, allowing different queue backends.

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
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
```

AsyncActors reference transport by name:
```yaml
spec:
  transport: sqs  # or rabbitmq
```

## Transport Interface

Sidecar implements:
- `Consume(queueName)`: Receive messages from queue
- `Send(queueName, envelope)`: Send envelope to queue
- `Ack(message)`: Acknowledge successful processing
- `Nack(message)`: Negative acknowledge (requeue)

## Queue Management

Queues automatically created by operator when AsyncActor reconciled.

**Queue naming**: `asya-{actor-name}`

**Lifecycle**:
- Created when AsyncActor created
- Deleted when AsyncActor deleted
- Preserved when AsyncActor updated

## Adding New Transport

1. Implement transport interface in `src/asya-sidecar/internal/transport/`
2. Add transport configuration to operator
3. Add KEDA scaler configuration
4. Update documentation

See [../../../src/asya-sidecar/internal/transport/](../../../src/asya-sidecar/internal/transport/) for implementation examples.
