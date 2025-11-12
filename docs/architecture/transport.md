# Transport Layer

Asya🎭 uses a pluggable transport abstraction for message routing between actors.

## Overview

The transport layer provides a consistent interface for sidecars to send and receive messages, regardless of the underlying message broker. Each sidecar independently resolves actor names to transport-specific queue identifiers using a **stateless, deterministic transformation**.

## Design Philosophy

- **No central registry**: No single point of failure or distributed state
- **Deterministic**: Same actor name always resolves to same queue identifier
- **Decentralized**: Each sidecar computes queue names independently
- **Transport-agnostic**: Easy to add new message brokers

## Transport Interface

```go
type Transport interface {
    Receive(ctx context.Context, queueName string) (QueueMessage, error)
    Send(ctx context.Context, queueName string, body []byte) error
    Ack(ctx context.Context, msg QueueMessage) error
    Nack(ctx context.Context, msg QueueMessage) error
    Close() error
}
```

## Actor Name Resolution

Sidecars use the `resolveQueueName()` function to transform actor names (from envelope route actors) into transport-specific queue identifiers.

### Resolution Algorithm

The sidecar's `resolveQueueName()` method implements the transformation:

```go
func (r *Router) resolveQueueName(actorName string) string {
    switch r.cfg.TransportType {
    case "rabbitmq":
        return actorName
    case "sqs":
        if r.cfg.SQSBaseURL == "" {
            return actorName
        }
        return fmt.Sprintf("%s/%s", r.cfg.SQSBaseURL, actorName)
    default:
        return actorName
    }
}
```

### Where Resolution Happens

Queue name resolution is applied in three places:

1. **Route to next actor** (`routeResponse`): Resolves the next actor in the route
2. **Route to happy-end** (`sendToHappyQueue`): Resolves end success queue
3. **Route to error-end** (`sendToErrorQueue`): Resolves end error queue

### End Queues

End queues (`happy-end`, `error-end`) are also resolved using the same algorithm, ensuring consistent naming across all message destinations.

## Multi-Transport Deployments

You can run different actors with different transports in the same cluster. Transports are configured at operator installation time in `deploy/helm-charts/asya-operator/values.yaml`:

**Operator configuration** (values.yaml):
```yaml
transports:
  rabbitmq:
    enabled: true
    type: rabbitmq
    config:
      host: rabbitmq.default.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-secret
        key: password

  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
      queueBaseUrl: https://sqs.us-east-1.amazonaws.com/123456789
      visibilityTimeout: 300
      waitTimeSeconds: 20
```

**Actor references transport by name:**
```yaml
spec:
  transport: rabbitmq  # or sqs
```

**Important**: All actors in the same **envelope route** must use the same transport type, as messages flow sequentially through the route actors.

## Supported Transports

- [RabbitMQ](transports/rabbitmq.md) - Identity mapping (actor name = queue name)
- [AWS SQS](transports/sqs.md) - URL construction (base URL + actor name)

## Adding New Transports

Future transports (Kafka, NATS, Pub/Sub) can be added by:

1. Implementing the `Transport` interface in `src/asya-sidecar/internal/transport/`
2. Adding resolution logic to `resolveQueueName()` in `src/asya-sidecar/internal/router/router.go`
3. Adding configuration fields to `Config` struct in `src/asya-sidecar/internal/config/config.go`
4. Adding KEDA trigger support in operator (`operator/internal/controller/keda.go`)
5. Updating CRD with new transport type in `operator/api/v1alpha1/asya_types.go`
6. Adding tests to `src/asya-sidecar/internal/router/router_test.go`

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ASYA_TRANSPORT` | No | `rabbitmq` | Transport type (`rabbitmq`, `sqs`) |

See individual transport documentation for transport-specific environment variables.

## Example: Multi-Actor Route

Given a route with actors: `["preprocessor", "analyzer", "reporter"]`

**RabbitMQ:**
```
preprocessor → analyzer → reporter → happy-end
```

**SQS (with base URL `https://sqs.us-east-1.amazonaws.com/123`):**
```
https://sqs.us-east-1.amazonaws.com/123/preprocessor
→ https://sqs.us-east-1.amazonaws.com/123/analyzer
→ https://sqs.us-east-1.amazonaws.com/123/reporter
→ https://sqs.us-east-1.amazonaws.com/123/happy-end
```

## See Also

- [RabbitMQ Transport](transports/rabbitmq.md) - RabbitMQ implementation details
- [SQS Transport](transports/sqs.md) - AWS SQS implementation details
- [Sidecar Component](asya-sidecar.md) - Sidecar architecture and configuration
- [Operator Component](asya-operator.md) - How operators configure transports
- [Transport Interface](../../src/asya-sidecar/internal/transport/transport.go) - Code reference
