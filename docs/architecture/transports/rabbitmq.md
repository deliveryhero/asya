# RabbitMQ Transport

RabbitMQ transport implementation for Asya🎭.

## Overview

RabbitMQ uses **identity mapping** for queue name resolution: the actor name directly equals the queue name.

**Example:**
- Actor: `image-processor`
- Queue: `image-processor`

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

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ASYA_TRANSPORT` | No | `rabbitmq` | Transport type |
| `ASYA_RABBITMQ_HOST` | Yes | - | RabbitMQ host |
| `ASYA_RABBITMQ_PORT` | No | `5672` | RabbitMQ port |
| `ASYA_RABBITMQ_USERNAME` | Yes | - | RabbitMQ username |
| `ASYA_RABBITMQ_PASSWORD` | Yes | - | RabbitMQ password |
| `ASYA_RABBITMQ_VHOST` | No | `/` | RabbitMQ virtual host |

### Operator Configuration

Configure RabbitMQ transport in `deploy/helm-charts/asya-operator/values.yaml`:

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
      vhost: /
```

### AsyncActor Configuration

Reference RabbitMQ transport in AsyncActor CRD:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: image-processor
spec:
  transport: rabbitmq
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-image-processor:latest
```

## Queue Management

RabbitMQ queues are automatically managed by the operator:

- **Queue naming**: `{actor-name}` (e.g., `image-processor`)
- **Queue declaration**: Automatic on first connection
- **Durability**: Queues are durable (survive broker restarts)
- **Auto-delete**: Disabled (queues persist when no consumers)

## Message Properties

- **Delivery Mode**: Persistent (messages survive broker restarts)
- **Content Type**: `application/json`
- **Routing Key**: Same as queue name
- **Exchange**: Direct exchange (default)

## Payload Size Limits

RabbitMQ supports large payloads:
- **Default limit**: 128 MB
- **Configurable**: Up to 2 GB (via `max_message_size`)
- **Recommendation**: < 10 MB for optimal performance

For payloads > 10 MB, consider using S3 references instead of embedding data in messages.

## Connection Management

### Connection Pooling

Each sidecar maintains a single persistent connection to RabbitMQ with:
- **Prefetch count**: Configurable (default: 1)
- **Heartbeat**: 60 seconds
- **Reconnection**: Automatic with exponential backoff

### Graceful Shutdown

On pod termination:
1. Stop accepting new messages
2. Process in-flight messages (up to graceful shutdown timeout)
3. Close connection cleanly

## Error Handling

### Message Acknowledgment

- **ACK**: Message processed successfully → removed from queue
- **NACK**: Processing failed → message requeued
- **Reject**: Unrecoverable error → message sent to DLQ (if configured)

### Dead Letter Queue

Configure DLQ in RabbitMQ for failed messages:

```yaml
# RabbitMQ policy (apply via management API or config)
rabbitmqctl set_policy DLQ ".*" '{"dead-letter-exchange":"dlx"}' --apply-to queues
```

## Performance Tuning

### Prefetch Count

Control concurrent message processing per sidecar:

```yaml
spec:
  sidecar:
    env:
    - name: ASYA_RABBITMQ_PREFETCH_COUNT
      value: "10"  # Process up to 10 messages concurrently
```

**Guidelines**:
- Low (1-5): Memory-intensive workloads, GPU inference
- High (10-50): Fast, lightweight processing

### Queue Durability vs Performance

**Durable queues** (default):
- ✅ Survive broker restarts
- ❌ Slower (disk writes)

**Non-durable queues** (for ephemeral workloads):
- ✅ Faster (memory only)
- ❌ Lost on broker restart

## Monitoring

RabbitMQ metrics exposed via management API:
- Queue depth
- Consumer count
- Message rates (publish, deliver, ack)
- Connection status

KEDA scaler uses these metrics for autoscaling.

## Example: Multi-Actor Pipeline

```yaml
# Actor 1: Preprocessor
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: preprocessor
spec:
  transport: rabbitmq
  # ... workload spec

---
# Actor 2: Inference
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: inference
spec:
  transport: rabbitmq
  # ... workload spec

---
# Actor 3: Postprocessor
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: postprocessor
spec:
  transport: rabbitmq
  # ... workload spec
```

**Message flow:**
```
preprocessor queue → inference queue → postprocessor queue → happy-end queue
```

## Troubleshooting

### Connection Refused

**Symptom**: `connection refused` errors in sidecar logs

**Causes**:
- RabbitMQ service not running
- Incorrect host/port configuration
- Network policy blocking access

**Solution**:
```bash
# Test connectivity from pod
kubectl exec -it <pod> -- nc -zv rabbitmq.default.svc.cluster.local 5672
```

### Authentication Failed

**Symptom**: `authentication failed` errors

**Causes**:
- Incorrect username/password
- User doesn't have permissions for vhost

**Solution**:
```bash
# Verify credentials in secret
kubectl get secret rabbitmq-secret -o yaml

# Check RabbitMQ user permissions
rabbitmqctl list_user_permissions admin
```

### High Queue Depth

**Symptom**: Messages accumulating in queue, slow processing

**Causes**:
- Insufficient replicas
- Slow handler processing
- KEDA not scaling

**Solution**:
```bash
# Check KEDA scaling status
kubectl get scaledobject -n <namespace>

# Check actor pod count
kubectl get pods -l asya.sh/actor=<actor-name>

# Increase maxReplicas or decrease queueLength in scaling config
```

## See Also

- [Transport Overview](../transport.md) - Transport abstraction
- [SQS Transport](sqs.md) - Alternative transport
- [Sidecar Component](../asya-sidecar.md) - Sidecar internals
- [Operator Configuration](../asya-operator.md) - Operator setup
