---
description: "Pub/Sub transport: Google Cloud Pub/Sub configuration, Workload Identity, subscription setup"
---

# Pub/Sub

Google Cloud Pub/Sub managed messaging service for actor communication.

## Configuration

**Crossplane Composition Config** (XRD for transport configuration):

```yaml
apiVersion: asya.dev/v1alpha1
kind: PubSubTransport
metadata:
  name: pubsub-default
spec:
  projectId: my-gcp-project
  endpoint: ""  # Optional, for emulator testing
  topics:
    autoCreate: true  # Optional, defaults to true
  subscriptions:
    ackDeadlineSeconds: 300  # Optional, defaults to 300
    messageRetentionDuration: "604800s"  # Optional, defaults to 7 days
```

**Sidecar environment variables** (rendered by Crossplane composition):

- `ASYA_TRANSPORT=pubsub`
- `ASYA_PUBSUB_PROJECT_ID` → from `config.projectId`
- `ASYA_PUBSUB_ENDPOINT` → from `config.endpoint` (optional, for emulator)

## Topic and Subscription Creation

Crossplane Composition creates Pub/Sub topics and subscriptions automatically when AsyncActor is reconciled.

**Topic name**: `asya-{namespace}-{actor_name}`

**Subscription name**: `asya-{namespace}-{actor_name}` (same as topic name)

**Example**: Actor `text-processor` in namespace `default` → Topic `asya-default-text-processor`, Subscription `asya-default-text-processor`

## Service Account Permissions

**Sidecar permissions** (via Workload Identity or service account key):

```json
{
  "bindings": [
    {
      "role": "roles/pubsub.publisher",
      "members": [
        "serviceAccount:actor-sa@my-project.iam.gserviceaccount.com"
      ]
    },
    {
      "role": "roles/pubsub.subscriber",
      "members": [
        "serviceAccount:actor-sa@my-project.iam.gserviceaccount.com"
      ]
    }
  ]
}
```

**Required IAM permissions**:

- `pubsub.topics.publish`
- `pubsub.subscriptions.consume`
- `pubsub.subscriptions.get`

**Crossplane Provider permissions**:

```json
{
  "bindings": [
    {
      "role": "roles/pubsub.admin",
      "members": [
        "serviceAccount:crossplane-provider@my-project.iam.gserviceaccount.com"
      ]
    }
  ]
}
```

**KEDA permissions** (for autoscaling):

```json
{
  "bindings": [
    {
      "role": "roles/monitoring.viewer",
      "members": [
        "serviceAccount:keda-sa@my-project.iam.gserviceaccount.com"
      ]
    }
  ]
}
```

## KEDA Scaler

```yaml
triggers:
  - type: gcp-pubsub
    metadata:
      subscriptionName: asya-default-text-processor
      subscriptionSize: "5"
      credentialsFromEnv: GOOGLE_APPLICATION_CREDENTIALS
```

**Scaling behavior**: KEDA polls subscription metrics (undelivered message count) and scales actor replicas based on `subscriptionSize` target.

## Subscription Configuration

Default subscription settings (configured in Crossplane composition):

| Parameter | Value | Description |
|-----------|-------|-------------|
| `ackDeadlineSeconds` | `300` (5 minutes) | Time window to acknowledge message before redelivery |
| `messageRetentionDuration` | `604800s` (7 days) | How long unacknowledged messages are retained |
| `expirationPolicy.ttl` | `""` (never) | Subscription does not expire due to inactivity |

## Implementation Details

**Message delivery**: Sidecar uses synchronous `Pull` RPC (not streaming `StreamingPull`) to receive messages one at a time.

**Ack behavior**: `Ack()` sends `Acknowledge` RPC with ack ID to confirm processing.

**Nack behavior**: `Nack()` calls `ModifyAckDeadline` with `ackDeadlineSeconds: 0`, making the message immediately available for redelivery.

**Topic caching**: Sidecar caches `pubsub.Topic` instances to avoid repeated lookups.

**Delayed delivery**: Pub/Sub does not support delayed message delivery. `SendWithDelay()` returns `ErrDelayNotSupported`.

## DLQ Configuration

(Configuration details TBD)

Pub/Sub supports dead-letter topics for messages that fail repeated delivery attempts. DLQ setup via Crossplane composition is planned but not yet implemented.

## Workload Identity Setup

**Recommended for GKE deployments**: Use Workload Identity to bind Kubernetes service accounts to GCP service accounts.

```bash
# Create GCP service account
gcloud iam service-accounts create actor-sa \
  --project=my-project

# Grant Pub/Sub permissions
gcloud projects add-iam-policy-binding my-project \
  --member="serviceAccount:actor-sa@my-project.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

gcloud projects add-iam-policy-binding my-project \
  --member="serviceAccount:actor-sa@my-project.iam.gserviceaccount.com" \
  --role="roles/pubsub.subscriber"

# Bind to Kubernetes service account
gcloud iam service-accounts add-iam-policy-binding \
  actor-sa@my-project.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:my-project.svc.id.goog[default/actor-service-account]"

# Annotate Kubernetes service account
kubectl annotate serviceaccount actor-service-account \
  -n default \
  iam.gke.io/gcp-service-account=actor-sa@my-project.iam.gserviceaccount.com
```

**AsyncActor** must reference the annotated Kubernetes service account:

```yaml
spec:
  serviceAccountName: actor-service-account
```

## Pub/Sub Emulator (Testing)

For local testing, use the Pub/Sub emulator:

```bash
docker run -p 8085:8085 gcr.io/google.com/cloudsdktool/google-cloud-cli:latest \
  gcloud beta emulators pubsub start --host-port=0.0.0.0:8085
```

**Sidecar configuration**:

```yaml
env:
  - name: ASYA_PUBSUB_PROJECT_ID
    value: test-project
  - name: ASYA_PUBSUB_ENDPOINT
    value: pubsub-emulator:8085
```

**Known limitations**:

- Subscription updates fail due to emulator field mask case sensitivity (camelCase vs snake_case)
- Crossplane composition uses `managementPolicies: ["Create", "Observe", "Delete"]` when `ASYA_PUBSUB_ENDPOINT` is set to work around this

## Best Practices

- Use Workload Identity for pod-level GCP authentication (avoid service account keys)
- Set appropriate `ackDeadlineSeconds` longer than expected processing time
- Monitor subscription metrics (undelivered message count, oldest unacked message age)
- Use DLQ for poison messages (when DLQ support is added)
- Deploy topics in the same region as GKE cluster to reduce latency and egress costs
- Enable message ordering if sequential processing is required (via subscription configuration)

## Cost Considerations

- **Free tier**: 10 GB message throughput per month
- **After free tier**: $40 per TiB ingress, $40 per TiB egress
- **Subscription storage**: $0.27 per GiB-month for retained unacknowledged messages
- **Seeks**: $0.01 per seek operation (replay from timestamp)
- **Scale to zero**: Subscriptions persist — minimal cost when idle

**See**: [Google Cloud Pub/Sub Pricing](https://cloud.google.com/pubsub/pricing)

## Troubleshooting

**`PermissionError`**: Verify Workload Identity binding and IAM permissions (`pubsub.topics.publish`, `pubsub.subscriptions.consume`).

**`NotFoundError` on send**: Topic does not exist. Verify Crossplane composition created the topic.

**`NotFoundError` on receive**: Subscription does not exist. Verify Crossplane composition created the subscription.

**Messages not being acknowledged**: Check `ackDeadlineSeconds` is longer than processing time. Increase if needed.

**KEDA not scaling**: Verify KEDA service account has `monitoring.viewer` role. Check subscription metrics in GCP Console.

**Emulator connection failed**: Verify `ASYA_PUBSUB_ENDPOINT` is reachable from sidecar pod. Use Kubernetes service name for in-cluster emulator.

**Subscription update fails in emulator**: Expected behavior — emulator has field mask case sensitivity issue. Crossplane composition skips updates when emulator is detected.

## Related Documentation

- [Transports Overview](README.md)
- [SQS Transport](sqs.md)
- [RabbitMQ Transport](rabbitmq.md)
- [Google Cloud Pub/Sub Documentation](https://cloud.google.com/pubsub/docs)
- [KEDA GCP Pub/Sub Scaler](https://keda.sh/docs/2.18/scalers/gcp-pub-sub/)
