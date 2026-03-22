# Scale Zero to Infinity

Asya actors scale independently based on their own queue depth. When there is no
work, pods scale to zero. When messages arrive, pods spin up in seconds. This is
particularly valuable for GPU inference workloads where idle pods are expensive.

## How it works

Each actor gets its own [KEDA](https://keda.sh/) `ScaledObject` with independent configuration:

- **Min replicas** — typically 0 for bursty workloads, 1 for always-on actors
- **Max replicas** — upper bound for resource protection
- **Queue depth threshold** — how many pending messages trigger a scale-up

KEDA polls the queue backend (SQS, RabbitMQ, Pub/Sub) and adjusts replica count
based on the number of pending messages. No central autoscaler is involved — each
actor scales autonomously.

## Why this matters for AI workloads

GPU instances are the most expensive resources in a Kubernetes cluster. A typical
AI pipeline has multiple stages, but only the inference actors need GPUs. With
Asya:

- Preprocessing actors run on cheap CPU nodes
- GPU inference actors scale to zero between batches
- Postprocessing actors scale independently of inference

Each actor's scaling is tuned to its own resource profile and workload pattern.

## Example: AsyncActor scaling configuration

```yaml
spec:
  scaling:
    minReplicaCount: 0      # scale to zero when queue is empty
    maxReplicaCount: 50     # handle burst traffic
    queueLength: 5          # target messages per replica
    pollingInterval: 15     # check queue every 15s
```

When the queue has 25 messages and `queueLength` is 5, KEDA creates 5 replicas.
When the queue drains, replicas scale back to 0 after the cooldown period.

## No central autoscaler bottleneck

Because KEDA ScaledObjects are per-actor, there is no shared autoscaler making
global decisions. Actor A can scale from 0 to 10 while Actor B stays at 0. The
decisions are local and fast.

## Scale-up latency

Cold start time depends on the container image and node availability:

- **Warm node, cached image**: 2-5 seconds
- **Warm node, pull required**: 10-30 seconds
- **Node scale-up required**: 1-3 minutes (depends on cloud provider)

For latency-sensitive actors, set `minReplicaCount: 1` to keep one pod warm.

## Further reading

- [Autoscaling setup guide](../setup/guide-autoscaling.md) — KEDA configuration,
  thresholds, and tuning
- [Actor Mesh](actor-mesh.md) — how independent scaling fits the choreography
  model
