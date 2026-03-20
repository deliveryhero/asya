<!-- Type: Reference -->
# Scaling

This page covers practical scaling configuration for AsyncActor workloads.
For KEDA internals and the autoscaling architecture, see [architecture/autoscaling.md](../architecture/autoscaling.md).

## Queue-based Autoscaling (KEDA)

Each `AsyncActor` gets a KEDA `ScaledObject` that reads queue depth and adjusts replica count:

```yaml
spec:
  scaling:
    enabled: true
    minReplicaCount: 0      # Scale to zero when idle
    maxReplicaCount: 50     # Max replicas
    queueLength: 5          # Target: N messages per replica
    pollingInterval: 10     # Check queue every 10s
    cooldownPeriod: 60      # Wait 60s before scaling down
```

**Formula**: `desiredReplicas = ceil(queueDepth / queueLength)`

**Example**: 100 messages, `queueLength: 5` -> 20 replicas. With `queueLength: 20` -> 5 replicas.

## Parameter Reference

| Parameter | Default | Description |
|---|---|---|
| `scaling.enabled` | `false` | Enable KEDA autoscaling |
| `scaling.minReplicaCount` | `0` | Minimum pod count (0 enables scale-to-zero) |
| `scaling.maxReplicaCount` | `50` | Maximum pod count |
| `scaling.queueLength` | `5` | Target messages per replica |
| `scaling.pollingInterval` | `10` | Seconds between queue depth checks |
| `scaling.cooldownPeriod` | `60` | Seconds to wait before scaling down after load drops |

### Advanced Parameters

For fine-grained KEDA behavior, use `scaling.advanced`:

| Parameter | Type | Description |
|---|---|---|
| `advanced.restoreToOriginalReplicaCount` | bool | Restore original replica count when ScaledObject is deleted |
| `advanced.formula` | string | Composite metric formula (must reference trigger name `queue`) |
| `advanced.target` | string | Target value for composite formula (required with `formula`) |
| `advanced.activationTarget` | string | Minimum metric value before scaling activates |
| `advanced.metricType` | string | `AverageValue`, `Value`, or `Utilization` |

See [architecture/autoscaling.md](../architecture/autoscaling.md) for advanced scaling modifier details and formula syntax.

## Choosing Scaling Parameters

### queueLength -- the key tradeoff

`queueLength` controls how aggressively you scale. Lower values mean more pods and higher throughput
at higher cost; higher values mean fewer pods and lower cost at higher latency.

**Rules of thumb**:

- **Fast handlers** (< 1s per message): use `queueLength: 10-20`. Each pod processes messages quickly,
  so batching more per pod is efficient.
- **Slow handlers** (> 10s per message, e.g. LLM inference): use `queueLength: 1-3`. Each message
  takes a long time, so you want near-1:1 pod-to-message ratio to minimize queue wait.
- **GPU workloads**: use `queueLength: 1`. GPU pods are expensive, but idle queue time on a GPU
  pod is even more expensive.

### pollingInterval

How often KEDA checks the queue. Lower values mean faster reaction but more API calls to
the queue backend.

- **Default (10s)** works for most workloads.
- **Reduce to 5s** for latency-sensitive workloads where fast scale-up matters.
- **Increase to 30s** for batch workloads where a few seconds of queue latency is acceptable.

### cooldownPeriod

How long KEDA waits after the queue is empty before scaling down. Prevents thrashing
when messages arrive in short bursts.

- **Default (60s)** works for steady traffic.
- **Increase to 120-300s** for bursty traffic with intervals of 1-5 minutes between bursts.
  Avoids constant scale-up/scale-down cycles.
- **Decrease to 30s** when cost savings from fast scale-down outweigh the cold-start penalty.

### minReplicaCount

- **0** (scale-to-zero): best for cost, but first message after idle pays a cold-start penalty
  (pod scheduling + image pull + init). Typical cold start: 5-30s depending on image size.
- **1**: always-warm. Eliminates cold start for the first message. Good for user-facing actors
  where latency matters.
- **> 1**: use for actors that need a minimum throughput baseline (e.g., always handle at least
  N messages/second).

## Common Scaling Scenarios

### Bursty Traffic

A pipeline receives 0 messages most of the time, then 500+ in a burst (e.g., batch job completion,
scheduled data drops).

```yaml
spec:
  scaling:
    enabled: true
    minReplicaCount: 0
    maxReplicaCount: 100
    queueLength: 1          # Scale aggressively during bursts
    pollingInterval: 5       # Detect burst quickly
    cooldownPeriod: 120      # Stay warm between burst waves
```

### GPU Workloads

LLM inference actors on GPU nodes. Each message takes 10-60s to process.

```yaml
spec:
  scaling:
    enabled: true
    minReplicaCount: 0
    maxReplicaCount: 10
    queueLength: 1           # One message per GPU pod
    pollingInterval: 10
    cooldownPeriod: 300       # GPU pods are slow to start; avoid thrashing
  resources:
    limits:
      nvidia.com/gpu: 1
  nodeSelector:
    nvidia.com/gpu: "true"
  tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
```

With `minReplicaCount: 0`, GPU actors scale to zero between bursts -- no idle GPU cost.

### Multi-Queue Pipeline

A pipeline with fast preprocessing, slow inference, and fast postprocessing.
Each actor scales independently based on its own queue depth:

```
preprocessor (queueLength: 10) -> inferencer (queueLength: 1) -> postprocessor (queueLength: 10)
```

The inferencer queue will be the bottleneck. KEDA scales it independently,
so it gets more replicas while pre/post stages stay lean.

### Latency-Sensitive User-Facing Actor

An actor that serves interactive requests where cold start is unacceptable.

```yaml
spec:
  scaling:
    enabled: true
    minReplicaCount: 1       # Always keep one pod warm
    maxReplicaCount: 20
    queueLength: 3
    pollingInterval: 5
    cooldownPeriod: 60
```

## Cost Optimization

**`queueLength` trades cost for speed**:

| `queueLength` | 100 messages -> pods | Throughput | Cost |
|---|---|---|---|
| 1 | 100 | Highest | Highest |
| 5 | 20 | High | High |
| 10 | 10 | Medium | Medium |
| 20 | 5 | Low | Low |

Set based on per-message processing time and your latency budget.

**Spot/preemptible instances** (AWS/GCP): Actors tolerate interruption well because messages
re-queue on pod termination. Use spot/preemptible nodes for actors with `minReplicaCount: 0`.
GPU actors on spot instances can cut costs by 60-90%.

## Monitoring Scaling Behavior

Check current scaling state:

```bash
# Watch HPA status (replica count, current/target metrics)
kubectl get hpa -w

# View ScaledObject status and conditions
kubectl get scaledobject <actor-name> -o yaml

# View KEDA external metrics
kubectl get --raw /apis/external.metrics.k8s.io/v1beta1
```

Key things to watch:

- **Frequent scale-up/scale-down cycles**: increase `cooldownPeriod`
- **Queue depth growing faster than pods**: decrease `queueLength` or increase `maxReplicaCount`
- **Pods idle with empty queue**: increase `queueLength` or decrease `cooldownPeriod`

For metrics and dashboards, see [monitoring.md](monitoring.md) and
[architecture/observability.md](../architecture/observability.md).
