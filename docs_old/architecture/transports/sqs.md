# AWS SQS Transport

AWS SQS (Simple Queue Service) transport implementation for Asya🎭.

## Overview

SQS uses **URL construction** for queue name resolution: combines base URL with actor name.

**Example:**
- Actor: `image-processor`
- Base URL: `https://sqs.us-east-1.amazonaws.com/123456789`
- Queue: `https://sqs.us-east-1.amazonaws.com/123456789/image-processor`

**Fallback**: If `ASYA_SQS_BASE_URL` is empty, uses identity mapping (actor name = queue name).

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ASYA_TRANSPORT` | Yes | - | Set to `sqs` |
| `ASYA_SQS_BASE_URL` | No | - | SQS queue base URL (without trailing slash) |
| `ASYA_SQS_REGION` | No | `us-east-1` | AWS region |
| `ASYA_SQS_VISIBILITY_TIMEOUT` | No | `300` | Message visibility timeout (seconds) |
| `ASYA_SQS_WAIT_TIME` | No | `20` | Long polling wait time (seconds) |

### Operator Configuration

Configure SQS transport in `deploy/helm-charts/asya-operator/values.yaml`:

```yaml
transports:
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
      queueBaseUrl: https://sqs.us-east-1.amazonaws.com/123456789
      visibilityTimeout: 300
      waitTimeSeconds: 20
```

### AsyncActor Configuration

Reference SQS transport in AsyncActor CRD:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: image-processor
spec:
  transport: sqs
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-image-processor:latest
```

## Queue Management

SQS queues must be created before deploying actors:

### Queue Naming Convention

**Pattern**: `asya-{actor-name}`

**Examples**:
- Actor `image-processor` → Queue `asya-image-processor`
- Actor `text-analyzer` → Queue `asya-text-analyzer`

**Why `asya-` prefix?**
- Enables fine-grained IAM policies: `arn:aws:sqs:*:*:asya-*`
- Avoids naming conflicts with other SQS queues
- Clear ownership for lifecycle management

### Queue Creation

**Option 1: Terraform**
```hcl
resource "aws_sqs_queue" "asya_actor" {
  name                       = "asya-image-processor"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 1209600  # 14 days
  receive_wait_time_seconds  = 20       # Long polling

  # Optional: Dead Letter Queue
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.asya_dlq.arn
    maxReceiveCount     = 5
  })

  tags = {
    ManagedBy = "asya-operator"
    Actor     = "image-processor"
  }
}
```

**Option 2: AWS CLI**
```bash
aws sqs create-queue \
  --queue-name asya-image-processor \
  --region us-east-1 \
  --attributes VisibilityTimeout=300,ReceiveMessageWaitTimeSeconds=20
```

**Option 3: Operator auto-creation** (planned, not yet implemented)

### Queue Lifecycle

- **Creation**: Manual (before actor deployment)
- **Deletion**: Manual (after actor deletion)
- **Retention**: 14 days (configurable)

## Authentication

### IAM Permissions

Sidecars require the following IAM permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:SendMessage",
        "sqs:GetQueueAttributes",
        "sqs:ChangeMessageVisibility"
      ],
      "Resource": "arn:aws:sqs:*:*:asya-*"
    }
  ]
}
```

### EKS Pod Identity (Recommended)

Associate IAM role with ServiceAccount:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: asya-actor-sa
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789:role/asya-actor-role
```

Reference in AsyncActor:

```yaml
spec:
  workload:
    template:
      spec:
        serviceAccountName: asya-actor-sa
```

### IRSA (IAM Roles for Service Accounts)

Alternative to Pod Identity for older EKS versions. Configure similarly with OIDC provider.

## Payload Size Limits

**Hard limit**: 256 KB per message

### Current Behavior

- ✅ Payloads < 256 KB: Work without modification
- ❌ Payloads > 256 KB: Fail with `PayloadTooLarge` error

### Workaround for Large Payloads

**SQS Extended Client Library pattern** (not yet implemented):

1. Upload payload > 256 KB to S3
2. Send S3 reference through SQS:
   ```json
   {
     "s3Bucket": "asya-payloads",
     "s3Key": "envelope-abc123.json"
   }
   ```
3. Sidecar downloads from S3 on receive

**Current recommendation**: Use RabbitMQ for payloads > 256 KB.

## Message Properties

- **Message Format**: JSON envelope structure
- **Message Attributes**: None (envelope contains all metadata)
- **Deduplication**: Not enabled (use Standard queues)
- **FIFO**: Not supported (Standard queues only)

## Connection Management

### Long Polling

SQS uses long polling to reduce empty receives:

```yaml
waitTimeSeconds: 20  # Wait up to 20s for messages
```

**Benefits**:
- Reduces API calls (cost savings)
- Decreases latency for incoming messages
- More efficient than short polling

### Visibility Timeout

Message becomes invisible to other consumers while processing:

```yaml
visibilityTimeout: 300  # 5 minutes
```

**Guidelines**:
- Set to **2x expected processing time**
- Too short: Duplicate processing
- Too long: Slow error recovery

### Graceful Shutdown

On pod termination:
1. Stop receiving new messages
2. Process in-flight messages (up to visibility timeout)
3. Messages auto-return to queue if not deleted

## Error Handling

### Message Acknowledgment

- **Delete**: Message processed successfully → removed from queue
- **No action**: Processing failed → message returns after visibility timeout
- **Change visibility**: Extend processing time if needed

### Dead Letter Queue

Configure DLQ for messages that fail repeatedly:

```hcl
resource "aws_sqs_queue" "asya_dlq" {
  name = "asya-image-processor-dlq"
}

resource "aws_sqs_queue" "asya_actor" {
  name = "asya-image-processor"

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.asya_dlq.arn
    maxReceiveCount     = 5  # Move to DLQ after 5 failures
  })
}
```

## Performance Tuning

### Receive Message Wait Time

Long polling duration:

```yaml
waitTimeSeconds: 20  # Recommended: 10-20 seconds
```

### Visibility Timeout

Based on processing time:

```yaml
visibilityTimeout: 600  # 10 minutes for slow workloads
```

### Batch Size

SQS allows receiving up to 10 messages per request (not yet implemented in Asya🎭 - currently receives 1 message at a time).

## Cost Optimization

### Long Polling

Reduces API calls → reduces costs:
- Short polling (0s wait): ~1M requests/hour (expensive)
- Long polling (20s wait): ~180K requests/hour (cheaper)

### Message Batching

Batch operations reduce costs (future enhancement):
- SendMessageBatch: Up to 10 messages/request
- DeleteMessageBatch: Up to 10 messages/request

### Queue Purging

Purge test queues after testing to avoid retention costs:

```bash
aws sqs purge-queue --queue-url https://sqs.us-east-1.amazonaws.com/123/asya-test-actor
```

## Monitoring

### CloudWatch Metrics

Monitor SQS queues via CloudWatch:
- `ApproximateNumberOfMessages`: Queue depth
- `ApproximateAgeOfOldestMessage`: Processing lag
- `NumberOfMessagesSent`: Throughput
- `NumberOfMessagesDeleted`: Successful processing

### KEDA Scaling

KEDA uses `ApproximateNumberOfMessages` for autoscaling:

```yaml
spec:
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    queueLength: 5  # Scale 1 replica per 5 messages
```

## Example: Multi-Actor Pipeline

```yaml
# Actor 1: Preprocessor
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: preprocessor
spec:
  transport: sqs
  # ... workload spec

---
# Actor 2: Inference
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: inference
spec:
  transport: sqs
  # ... workload spec
```

**Required SQS queues:**
- `asya-preprocessor`
- `asya-inference`
- `asya-happy-end` (crew actor)
- `asya-error-end` (crew actor)

**Message flow:**
```
asya-preprocessor → asya-inference → asya-happy-end
```

## Troubleshooting

### Queue Not Found

**Symptom**: `QueueDoesNotExist` errors in sidecar logs

**Causes**:
- Queue not created before actor deployment
- Incorrect queue naming
- Wrong AWS region

**Solution**:
```bash
# Verify queue exists
aws sqs list-queues --region us-east-1 --queue-name-prefix asya-

# Create missing queue
aws sqs create-queue --queue-name asya-{actor-name} --region us-east-1
```

### Access Denied

**Symptom**: `AccessDenied` or `InvalidClientTokenId` errors

**Causes**:
- Missing IAM permissions
- ServiceAccount not associated with IAM role
- IRSA/Pod Identity misconfiguration

**Solution**:
```bash
# Verify ServiceAccount annotation
kubectl get sa asya-actor-sa -o yaml

# Test IAM permissions from pod
kubectl exec -it <pod> -- aws sqs list-queues --region us-east-1
```

### Payload Too Large

**Symptom**: `PayloadTooLarge` error, messages not sent

**Causes**:
- Envelope + payload > 256 KB

**Solution**:
- Switch to RabbitMQ transport
- Reduce payload size (compress, truncate)
- Wait for S3 extended client pattern (future)

### High Visibility Timeout Errors

**Symptom**: Duplicate processing, same message processed multiple times

**Causes**:
- Visibility timeout too short
- Processing time > visibility timeout

**Solution**:
```yaml
# Increase visibility timeout
spec:
  sidecar:
    env:
    - name: ASYA_SQS_VISIBILITY_TIMEOUT
      value: "600"  # 10 minutes
```

## Migration from RabbitMQ

### Compatibility

Both transports use the same envelope protocol - switching requires:

1. **Queue creation**: Create SQS queues for all actors
2. **IAM setup**: Configure IAM roles and policies
3. **Update transport reference**: Change `transport: rabbitmq` → `transport: sqs`
4. **Redeploy actors**: Apply updated AsyncActor CRDs

### Limitations vs RabbitMQ

| Feature | RabbitMQ | SQS |
|---------|----------|-----|
| Max payload size | 128 MB (default) | 256 KB |
| Message ordering | Not guaranteed | Not guaranteed |
| Message TTL | Configurable | 14 days max |
| DLQ | Via exchange config | Native support |
| Cost | Infrastructure cost | Per-request pricing |

## See Also

- [Transport Overview](../transport.md) - Transport abstraction
- [RabbitMQ Transport](rabbitmq.md) - Alternative transport
- [Sidecar Component](../asya-sidecar.md) - Sidecar internals
- [AWS IAM Setup](../../guides/deployment-aws-setup.md) - IAM configuration guide
