# Scaling

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

**Example**: 100 messages, `queueLength: 5` → 20 replicas. With `queueLength: 20` → 5 replicas.

## GPU Workloads

```yaml
spec:
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

Ensure the GPU node group exists and the NVIDIA device plugin is installed in your cluster.

With `minReplicaCount: 0`, GPU actors scale to zero between bursts — no idle GPU cost.

## Cost Optimization

**`queueLength` trades cost for speed**:

| `queueLength` | 100 messages → pods | Throughput | Cost |
|---|---|---|---|
| 5 | 20 | High | High |
| 10 | 10 | Medium | Medium |
| 20 | 5 | Low | Low |

Set based on per-message processing time and your latency budget.

**Spot instances** (AWS): GPU actors tolerate interruption well because messages re-queue on pod
termination. Use spot/preemptible nodes for actors with `minReplicaCount: 0`.

**See**: [architecture/autoscaling.md](../architecture/autoscaling.md) for KEDA internals.
