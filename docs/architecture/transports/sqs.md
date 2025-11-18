# SQS Transport

AWS-managed message queue service.

## Configuration

**Operator config** (`deploy/helm-charts/asya-operator/values.yaml`):
```yaml
transports:
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
      endpoint: ""  # Optional, for LocalStack or custom SQS endpoints
      visibilityTimeout: 300  # Optional, seconds, defaults to 300 (5 minutes)
      waitTimeSeconds: 20  # Optional, long polling, defaults to 20
      queues:
        autoCreate: true  # Optional, defaults to true
        forceRecreate: false  # Optional, defaults to false
        dlq:
          enabled: true  # Optional
          maxRetryCount: 3  # Optional, defaults to 3
          retentionDays: 14  # Optional, defaults to 14
      tags:  # Optional, tags applied to created queues
        Environment: production
        Team: ml-platform
```

**AsyncActor reference**:
```yaml
spec:
  transport: sqs
```

**Sidecar environment variables** (injected by operator):

- `ASYA_TRANSPORT=sqs`
- `ASYA_AWS_REGION` → from `config.region`
- `ASYA_SQS_ENDPOINT` → from `config.endpoint` (optional)
- `ASYA_SQS_VISIBILITY_TIMEOUT` → from `config.visibilityTimeout` (optional)
- `ASYA_SQS_WAIT_TIME_SECONDS` → from `config.waitTimeSeconds` (optional)

## Queue Creation

Operator creates SQS queues automatically when AsyncActor is reconciled:

**Queue name**: `asya-{actor_name}`

**Example**: Actor `text-processor` → Queue `asya-text-processor`

**Queue URL**: `https://sqs.{region}.amazonaws.com/{account}/asya-{actor_name}`

## IAM Permissions

**Sidecar permissions** (via IRSA, Pod Identity, or instance role):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:SendMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl"
      ],
      "Resource": "arn:aws:sqs:*:*:asya-*"
    }
  ]
}
```

**Operator permissions**:
```json
{
  "Effect": "Allow",
  "Action": [
    "sqs:CreateQueue",
    "sqs:DeleteQueue",
    "sqs:SetQueueAttributes",
    "sqs:GetQueueAttributes",
    "sqs:GetQueueUrl",
    "sqs:TagQueue"
  ],
  "Resource": "arn:aws:sqs:*:*:asya-*"
}
```

**KEDA permissions** (for autoscaling):
```json
{
  "Effect": "Allow",
  "Action": [
    "sqs:GetQueueAttributes",
    "sqs:GetQueueUrl",
    "sqs:ListQueues"
  ],
  "Resource": "arn:aws:sqs:*:*:asya-*"
}
```

## KEDA Scaler

```yaml
triggers:

- type: aws-sqs-queue
  metadata:
    queueURL: https://sqs.us-east-1.amazonaws.com/.../asya-actor
    queueLength: "5"
    awsRegion: us-east-1
```

## DLQ Configuration

When `queues.dlq.enabled: true`, operator creates DLQ for each queue:

**DLQ name**: `asya-{actor_name}-dlq`

**Max receive count**: Configured via `queues.dlq.maxRetryCount` (default: 3)

**Retention**: Configured via `queues.dlq.retentionDays` (default: 14 days)

**Behavior**: Messages move to DLQ after exceeding max receive count.

## Implementation Details

**Long polling**: Sidecar uses `waitTimeSeconds` for efficient message retrieval (default: 20s)

**Visibility timeout**: Messages become invisible to other consumers for `visibilityTimeout` seconds (default: 300s)

**Nack behavior**: `Nack()` sets visibility timeout to 0, making message immediately available for redelivery

**Queue URL caching**: Sidecar caches resolved queue URLs to reduce API calls

**Reconnection**: SQS client supports automatic reconnection with exponential backoff

## Best Practices

- Use IRSA or Pod Identity for pod-level IAM permissions
- Set `visibilityTimeout` longer than expected processing time
- Monitor DLQ depth for stuck messages
- Use `asya-` prefix for IAM policy granularity
- Enable DLQ for production workloads
- Set appropriate `tags` for cost tracking

## Cost Considerations

- First 1M requests/month free
- $0.40 per million requests after
- No idle costs (pay per use)
- Scale to zero = $0

**See**: [AWS SQS Pricing](https://aws.amazon.com/sqs/pricing/)
