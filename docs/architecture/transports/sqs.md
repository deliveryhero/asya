# SQS Transport

AWS-managed message queue service.

## Configuration

**Operator config**:
```yaml
transports:
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
```

**AsyncActor reference**:
```yaml
spec:
  transport: sqs
```

## Queue Creation

Operator creates SQS queues automatically:

**Queue name**: `asya-{actor_name}`

**Example**: Actor `text-processor` → Queue `asya-text-processor`

**Queue URL**: `https://sqs.{region}.amazonaws.com/{account}/asya-{actor_name}`

## IAM Permissions

**Sidecar permissions** (via IRSA or instance role):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes"
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
    "sqs:GetQueueUrl"
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

SQS queues automatically configured with DLQ:

**DLQ name**: `asya-{actor_name}-dlq`

**Max receive count**: 3 (configurable)

Failed messages move to DLQ after 3 nacks.

## Best Practices

- Use IRSA for pod-level IAM permissions
- Set appropriate visibility timeout (default: 300s)
- Monitor DLQ depth for stuck messages
- Use `asya-` prefix for IAM policy granularity

## Cost Considerations

- First 1M requests/month free
- $0.40 per million requests after
- No idle costs (pay per use)
- Scale to zero = $0

**See**: [AWS SQS Pricing](https://aws.amazon.com/sqs/pricing/)
