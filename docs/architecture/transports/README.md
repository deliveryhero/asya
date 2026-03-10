# Transports

Asya supports pluggable message queue transports for actor communication.

## Overview

Transport layer is abstracted - sidecar implements transport interface, allowing different queue backends.

## Supported Transports

- **[SQS](sqs.md)**: AWS-managed queue service
- **[RabbitMQ](rabbitmq.md)**: Self-hosted open-source message broker
- **[Socket](socket.md)**: Unix domain sockets on a shared Docker volume — local testing only ⚠️

## Planned Transports

- **Kafka**: High-throughput distributed streaming
- **NATS**: Cloud-native messaging system
- **Google Pub/Sub**: GCP-managed messaging service

See [KEDA scalers](https://keda.sh/docs/2.18/scalers/) for potential integration targets.

## Transport Configuration

Transport type is specified in the AsyncActor XRD claim via the `transport` field. The Crossplane composition creates the appropriate queue resources.

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  transport: sqs  # Validated by XRD enum
```

## Transport Interface

Sidecar implements (`src/asya-sidecar/internal/transport/transport.go`):

- `Receive(ctx, queueName)`: Receive single message from queue (blocking with long polling)
- `Send(ctx, queueName, body)`: Send message body to queue
- `Ack(ctx, message)`: Acknowledge successful processing
- `Nack(ctx, message)`: Negative acknowledge (requeue or move to DLQ)

## Queue Management

Queues automatically created by operator when AsyncActor reconciled.

**Queue naming**: `asya-{namespace}-{actor_name}`

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
