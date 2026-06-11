---
description: "Pub/Sub external scaler: KEDA scaler for Pub/Sub, direct Pull API, replaces deprecated built-in"
---

# asya-scalers

KEDA external scalers for Asya transport backends.

## Problem

KEDA's built-in `gcp-pubsub` scaler queries Cloud Monitoring (Stackdriver) for
`subscription/num_undelivered_messages`. Cloud Monitoring has a 2-4 minute metric
ingestion lag (60s sampling + up to 120s visibility delay), making 0-to-1 scaling
unacceptably slow for latency-sensitive workloads. The scaler also does not work
with the Pub/Sub emulator (no Cloud Monitoring available).

## scaler-pubsub

A Go gRPC service implementing KEDA's `ExternalScaler` interface. Queries Pub/Sub
subscriptions directly via the Pull API, bypassing Cloud Monitoring entirely.

### How it works

| gRPC Method | Implementation | Latency |
|-------------|---------------|---------|
| `IsActive` | `Pull(maxMessages=1)` + nack | ~100ms |
| `GetMetricSpec` | Return metric name + target from metadata | instant |
| `GetMetrics` | `Pull(maxMessages=N)` + nack | ~100ms |
| `StreamIsActive` | Poll `IsActive` every 5s | 5s |

Messages are immediately nacked (ack deadline set to 0) so they remain available
for actual consumers. No messages are consumed or lost by the scaler.

### ScaledObject configuration

When the external scaler is enabled, the Crossplane composition generates:

```yaml
triggers:
- type: external
  name: queue
  metadata:
    scalerAddress: "asya-scaler-pubsub.asya-system.svc.cluster.local:6000"
    subscriptionName: "projects/PROJECT/subscriptions/asya-NAMESPACE-ACTOR"
    targetValue: "5"
```

Instead of the default `type: gcp-pubsub` trigger.

### Metadata parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `subscriptionName` | Full Pub/Sub subscription resource name | required |
| `targetValue` | Messages per replica (HPA target) | `5` |
| `maxMessages` | Max messages to pull for `GetMetrics` | `100` |
| `streamInterval` | Polling interval for `StreamIsActive` | `5s` |

### Authentication

The scaler authenticates to GCP Pub/Sub using:
- **GKE Workload Identity** (recommended): annotate the scaler's ServiceAccount
- **Service account key**: set `GOOGLE_APPLICATION_CREDENTIALS` env var
- **Pub/Sub emulator**: set `PUBSUB_EMULATOR_HOST` env var (no auth needed)

Required IAM permissions: `pubsub.subscriber` (Pull + ModifyAckDeadline).

### Deployment

The scaler is deployed via the `asya-crossplane` Helm chart:

```yaml
# values.yaml
pubsub:
  keda:
    scaler:
      enabled: true
      address: "asya-scaler-pubsub.asya-system.svc.cluster.local:6000"
      image:
        repository: ghcr.io/deliveryhero/asya-crew  # temporary
        tag: "0.6.0"
      serviceAccountName: "asya-scaler-pubsub"  # for Workload Identity
      env:
      - name: PUBSUB_EMULATOR_HOST              # for emulator
        value: "emulator:8085"
```

When `scaler.enabled=true`:
- A Deployment + Service (`asya-scaler-pubsub`) is created
- ScaledObjects use `type: external` instead of `type: gcp-pubsub`
- TriggerAuthentication is skipped (scaler handles auth)

### Docker image

The scaler ships in the standalone `ghcr.io/deliveryhero/asya-scalers` image,
which hosts one binary per scaler. The `/scaler-pubsub` binary is selected via
the container `command` override in the Crossplane chart's scaler Deployment.

### Environment variables

| Variable | Description |
|----------|-------------|
| `SCALER_PORT` | gRPC listen port (default: `6000`) |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARN`, `ERROR` (default: `INFO`) |
| `PUBSUB_EMULATOR_HOST` | Pub/Sub emulator address (bypasses GCP auth) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON key |

### Observability

The scaler exposes:
- gRPC health checks (used by K8s liveness/readiness probes)
- gRPC reflection (for debugging with `grpcurl`)
- Structured logging via `slog`
