---
description: "Pluggable transports: swap SQS, RabbitMQ, or Pub/Sub via Crossplane without code changes"
---

# Pluggable Transports

Asya separates message transport from application logic. The same handler code
runs on any supported queue backend — swapping transports is an infrastructure
change, not a code change.

## Supported transports

| Transport | Managed service | Self-hosted |
|-----------|----------------|-------------|
| **SQS** | AWS SQS | LocalStack, ElasticMQ |
| **RabbitMQ** | CloudAMQP, Amazon MQ | Any RabbitMQ cluster |
| **Pub/Sub** | GCP Pub/Sub | Pub/Sub emulator |
| **Socket** | — | Local development only |

## Transport is configuration, not code

The handler function has no knowledge of the underlying queue. Transport
selection happens in the `AsyncActor` manifest:

```yaml
spec:
  transport:
    type: sqs
    queue: my-actor-queue
```

Changing from SQS to RabbitMQ means updating this YAML block. The handler, the
sidecar behavior, and the scaling logic all remain identical.

## Crossplane abstracts provisioning

When using Crossplane Compositions, the queue itself is provisioned
declaratively. Creating an `AsyncActor` resource automatically provisions the
backing queue, configures KEDA scaling, and wires the sidecar to the correct
endpoint.

## Socket transport for local development

The Socket transport uses Unix domain sockets for message passing. It requires
no cloud credentials and no external services, making it ideal for local testing
with Docker Compose.

## Same actor, different environments

A common pattern is to use Socket transport in development, RabbitMQ in staging,
and SQS in production. The handler code is identical across all three — only the
infrastructure configuration changes.

## Transport interface

Adding a new transport means implementing this Go interface
(`src/asya-sidecar/pkg/transport/transport.go`):

```go
type Transport interface {
    Receive(ctx context.Context, queueName string) (QueueMessage, error)
    Send(ctx context.Context, queueName string, body []byte) error
    SendWithDelay(ctx context.Context, queueName string, body []byte, delay time.Duration) error
    Ack(ctx context.Context, msg QueueMessage) error
    Requeue(ctx context.Context, msg QueueMessage) error
    Close() error
}
```

Each backend (SQS, RabbitMQ, Pub/Sub, Socket) provides its own implementation of
this interface. The sidecar selects the implementation based on the `transport.type`
field in the AsyncActor manifest.

## Further reading

- [Transport reference](../reference/transports/README.md) — configuration
  details for each transport backend
- [SQS transport](../reference/transports/sqs.md),
  [RabbitMQ transport](../reference/transports/rabbitmq.md),
  [Pub/Sub transport](../reference/transports/pubsub.md) — backend-specific
  setup
