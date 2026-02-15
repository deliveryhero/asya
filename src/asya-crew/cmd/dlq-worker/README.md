# x-dlq Worker

Standalone Go binary for processing transport-level Dead Letter Queue (DLQ) messages.

## Why a Separate DLQ Worker?

### The Problem

When a message lands in the transport DLQ (SQS DLQ, RabbitMQ DLX), it means the **sidecar itself failed** — a crash, panic, or unrecoverable transport error prevented normal message processing. The existing x-sink and x-sump actors cannot process DLQ messages because:

1. **x-sink and x-sump are AsyncActors** — they rely on the sidecar for message consumption. If the sidecar is the component that failed, routing DLQ messages through another sidecar-based actor creates a **circular dependency** on the failing component.
2. **Shared failure domain** — x-sink/x-sump use the same `transport.Transport` abstraction as the sidecar. A bug in that abstraction would affect DLQ processing identically.
3. **Different queue semantics** — DLQ messages arrive on transport-managed queues (SQS redrive policy, RabbitMQ dead-letter exchange), not on Asya-managed actor queues. The sidecar expects Asya message routing conventions.

### Decision: Independent Failure Domain (ADR-005)

The DLQ worker operates in a **completely separate failure domain** from the sidecar:

| Property | Sidecar / x-sink / x-sump | x-dlq Worker |
|----------|---------------------------|--------------|
| Runtime | Injected into actor pods | Standalone K8s Deployment |
| Transport SDK | `internal/transport` abstraction | Native `aws-sdk-go-v2` |
| Queue discovery | `GetQueueUrl` + cache + retry | Direct URL from config |
| Message format | Asya envelope expected | Best-effort JSON parse |
| Failure impact | Sidecar bug affects all actors | Independent binary |

### Alternatives Considered

| Alternative | Verdict | Reasoning |
|-------------|---------|-----------|
| **x-sink actor** | ❌ Rejected | Circular dependency: sidecar failure caused the DLQ event |
| **x-sump actor** | ❌ Rejected | Same circular dependency; x-sump has no gateway reporting |
| **SQS + EventBridge Pipes** | ❌ Deferred | Managed pipes can't propagate mTLS identity for future actor-to-actor auth |
| **AWS Lambda** | ❌ Deferred | Good for production Tier 1; requires per-cloud implementation; complex IAM |
| **Kafka Connect / Pub/Sub subscriptions** | ❌ Deferred | Transport-specific; doesn't generalize across SQS/RabbitMQ/NATS |
| **Standalone Go binary** | ✅ Chosen | Universal, transport-agnostic interface, same language as sidecar but zero shared code |

The standalone binary (Tier 2) is the universal fallback. Cloud-native managed solutions (Tier 1: EventBridge Pipes, Lambda) can be added later for production environments that don't need mTLS.

## Architecture

```
SQS Source Queue
  │ (message fails after maxReceiveCount)
  │ (SQS redrive policy)
  ▼
SQS DLQ Queue
  │
  ▼
┌──────────────────────────────────┐
│  x-dlq Worker (standalone Go)   │
│                                  │
│  1. Receive (native SQS SDK)    │
│  2. Parse message body → ID     │
│  3. POST /tasks/{id}/final ──────┼──→ Gateway (best-effort, 3 retries)
│  4. Persist message ─────────────┼──→ S3/MinIO  OR  stdout
│  5. ACK (delete from DLQ)       │
└──────────────────────────────────┘
```

**Processing guarantees:**
- S3 persistence (or stdout) must succeed before ACK
- Gateway reporting is best-effort (3 retries with 200ms backoff)
- Malformed messages (unparseable JSON, missing `id`) are ACKed to prevent infinite redelivery; full body is logged
- If S3 fails, the message stays in the DLQ for retry on next delivery

## Configuration

All configuration is via environment variables. No config files.

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `DLQ_QUEUE_URL` | Full SQS queue URL for the DLQ | `https://sqs.us-east-1.amazonaws.com/123456789/asya-prod-x-dlq` |
| `DLQ_TRANSPORT` | Transport type | `sqs` |
| `AWS_REGION` | AWS region (fallback for SQS_REGION and S3_REGION) | `us-east-1` |

### Optional — Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_BUCKET` | _(empty = stdout mode)_ | S3 bucket for message persistence. When unset, messages are written to stdout as structured log lines |
| `S3_ENDPOINT` | _(empty)_ | Custom S3 endpoint for MinIO or LocalStack |
| `S3_PREFIX` | `dlq/` | Key prefix for stored messages |
| `S3_REGION` | `$AWS_REGION` | S3 region (only required when S3_BUCKET is set) |

### Optional — Gateway

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_URL` | _(empty = disabled)_ | Gateway base URL for reporting failure status via `POST /tasks/{id}/final` |

### Optional — Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `SQS_REGION` | `$AWS_REGION` | SQS region (override if DLQ is in a different region) |
| `VISIBILITY_TIMEOUT` | `300` | SQS visibility timeout in seconds |
| `WAIT_TIME_SECONDS` | `20` | SQS long polling wait time in seconds |
| `LOG_LEVEL` | `INFO` | Log level: DEBUG, INFO, WARN, ERROR |

### Storage Modes

**stdout mode** (default when `S3_BUCKET` is unset):
Messages are written to stdout as structured log lines. Suitable for development, debugging, and environments where log aggregation (Loki, CloudWatch Logs) provides sufficient persistence.

**S3 mode** (when `S3_BUCKET` is set):
Messages are persisted to S3 under key `{S3_PREFIX}{date}/{message_id}.json`. Suitable for production environments requiring durable message archival for auditing or replay.

## Deployment

The DLQ worker is deployed as a regular Kubernetes Deployment (NOT an AsyncActor). It is included in the `asya-crew` Helm chart.

### Helm (via asya-crew chart)

The DLQ worker is enabled by default in the asya-crew Helm chart. Set `dlq-worker.config.queueURL` to activate it:

```yaml
# values.yaml override
asya-crew:
  dlq-worker:
    enabled: true
    config:
      queueURL: "https://sqs.us-east-1.amazonaws.com/123456789/asya-prod-x-dlq"
      transport: sqs
      # s3Bucket: ""       # stdout mode (default)
      # s3Bucket: my-bucket # S3 mode
      # gatewayURL: "http://asya-gateway:8080"
```

### AWS Credentials

The DLQ worker needs AWS credentials for SQS (and optionally S3). Options:

**IRSA (recommended for production):**
```yaml
asya-crew:
  dlq-worker:
    serviceAccount:
      create: true
      annotations:
        eks.amazonaws.com/role-arn: "arn:aws:iam::123456789:role/dlq-worker-role"
```

Required IAM permissions:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
      "Resource": "arn:aws:sqs:*:*:asya-*-x-dlq"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::my-bucket/dlq/*"
    }
  ]
}
```

**Static credentials (development/LocalStack):**
```yaml
asya-crew:
  dlq-worker:
    env:
      AWS_ACCESS_KEY_ID: "test"
      AWS_SECRET_ACCESS_KEY: "test"
```

### Manual Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dlq-worker
spec:
  replicas: 1
  selector:
    matchLabels:
      app: dlq-worker
  template:
    metadata:
      labels:
        app: dlq-worker
    spec:
      serviceAccountName: dlq-worker
      containers:
      - name: dlq-worker
        image: ghcr.io/deliveryhero/asya-dlq-worker:latest
        env:
        - name: DLQ_QUEUE_URL
          value: "https://sqs.us-east-1.amazonaws.com/123456789/asya-prod-x-dlq"
        - name: DLQ_TRANSPORT
          value: "sqs"
        - name: AWS_REGION
          value: "us-east-1"
        # Optional: S3 persistence
        # - name: S3_BUCKET
        #   value: "my-dlq-archive"
        # Optional: Gateway reporting
        # - name: GATEWAY_URL
        #   value: "http://asya-gateway:8080"
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 128Mi
```

## Building

```bash
# Build binary
make -C src/asya-crew/cmd/dlq-worker build

# Run unit tests
make -C src/asya-crew/cmd/dlq-worker test-unit

# Build Docker image
docker build -t asya-dlq-worker:latest src/asya-crew/cmd/dlq-worker/
```
