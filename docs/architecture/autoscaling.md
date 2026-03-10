# Autoscaling

## How KEDA Works

KEDA (Kubernetes Event Driven Autoscaling) monitors external metrics (queue depth, custom metrics) and scales Kubernetes Deployments.

**Components**:

- **KEDA Operator**: Watches ScaledObjects
- **Metrics Server**: Exposes metrics to HPA
- **ScaledObject**: Defines scaling triggers and targets

## Asya Integration

The Crossplane composition creates a KEDA ScaledObject for each AsyncActor:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: text-processor
spec:
  scaleTargetRef:
    name: text-processor   # Deployment to scale
  minReplicaCount: 0       # Scale to zero when idle
  maxReplicaCount: 50      # Max replicas
  triggers:
  - type: aws-sqs-queue
    metadata:
      queueURL: https://sqs.us-east-1.amazonaws.com/.../asya-text-processor
      queueLength: "5"      # Target: 5 messages per replica
      awsRegion: us-east-1
```

**Formula**: `desiredReplicas = ceil(queueDepth / queueLength)`

**Example**: 100 messages, queueLength=5 → 20 replicas

## Benefits

**Scale to zero**:

- 0 messages → 0 pods → $0 cost
- Queue fills → Spin up to maxReplicaCount in seconds

**Independent scaling**:

- Each actor scales based on its own queue depth
- Data-loader scales differently than LLM inference

**Cost optimization**:

- Only run GPU pods when needed
- No warm pools, no idle resources

**Handle bursts**:

- Automatic response to traffic spikes
- Gradual scale-down when load decreases

## Configuration

Scaling configured in AsyncActor spec:

```yaml
spec:
  scaling:
    enabled: true            # Enable KEDA autoscaling
    minReplicaCount: 0           # Minimum pods (0 for scale-to-zero)
    maxReplicaCount: 100         # Maximum pods
    queueLength: 5           # Target messages per replica
    cooldownPeriod: 60       # Seconds before scaling down (default: 60s)
    pollingInterval: 10      # How often KEDA checks queue depth (default: 10s)
```

**Parameters**:

- `enabled`: Enable/disable KEDA autoscaling (default: false)
- `minReplicaCount`: Minimum pods (default: 0 for scale-to-zero)
- `maxReplicaCount`: Maximum pods (default: 50)
- `queueLength`: Target messages per replica (default: 5)
- `cooldownPeriod`: Delay before scaling down in seconds (default: 60)
- `pollingInterval`: Queue check frequency in seconds (default: 10)

### Advanced Scaling Configuration

For fine-grained KEDA behavior, use the `scaling.advanced` sub-object:

```yaml
spec:
  scaling:
    minReplicaCount: 0
    maxReplicaCount: 20
    advanced:
      restoreToOriginalReplicaCount: true
      formula: "queue"
      target: "10"
      activationTarget: "1"
      metricType: AverageValue
```

**Parameters**:

| Field | Type | Description |
|-------|------|-------------|
| `restoreToOriginalReplicaCount` | bool | When true, replicas are restored to their value before the ScaledObject was created when the ScaledObject is deleted |
| `formula` | string | Composite metric formula combining multiple metrics (KEDA `scalingModifiers.formula`). Requires `target`. Formula must reference trigger names — Asya compositions name the primary trigger `queue`, so use `queue` to reference it. |
| `target` | string | Target value for the composite formula (required with `formula`) |
| `activationTarget` | string | Minimum metric value before scaling activates (avoids scaling at near-zero load) |
| `metricType` | `AverageValue` \| `Value` \| `Utilization` | Metric aggregation method for the composite formula |

**Formula trigger reference**: KEDA validates formula identifiers at admission time using `expr-lang`. Formulas must reference trigger names defined in `triggers[N].name`. Asya compositions set `name: queue` on the primary trigger, so `queue` is always a valid reference:

```yaml
advanced:
  formula: "queue"
  target: "5"
  activationTarget: "1"
  metricType: AverageValue
```

**Notes**:
- `formula`, `target`, `activationTarget`, and `metricType` map to `spec.advanced.scalingModifiers` in the KEDA ScaledObject
- `restoreToOriginalReplicaCount` maps to `spec.advanced.restoreToOriginalReplicaCount`
- `target` is required when `formula` is set; the XRD enforces this with a `oneOf` validation constraint

## Scaling Scenarios

### Idle Workload

- Queue: 0 messages
- Replicas: 0 (minReplicaCount=0)
- Cost: $0

### Low Load

- Queue: 10 messages, queueLength=5
- Replicas: 2
- Processing: ~5 messages per replica

### High Load

- Queue: 250 messages, queueLength=5
- Replicas: 50 (capped at maxReplicaCount)
- Processing: ~5 messages per replica

### Burst

- Queue suddenly: 500 messages
- KEDA scales up: 0 → 50 in ~30-60 seconds
- After processing: Queue drains → Scale down to 0

## Transport-Specific Triggers

### SQS

```yaml
triggers:

- type: aws-sqs-queue
  metadata:
    queueURL: https://sqs.us-east-1.amazonaws.com/.../asya-actor
    queueLength: "5"
    awsRegion: us-east-1
```

### RabbitMQ

```yaml
triggers:

- type: rabbitmq
  metadata:
    host: amqp://rabbitmq:5672
    queueName: asya-actor
    queueLength: "5"
```

## Monitoring Autoscaling

```bash
# Watch HPA status
kubectl get hpa -w

# View ScaledObject
kubectl get scaledobject text-processor -o yaml

# View KEDA metrics
kubectl get --raw /apis/external.metrics.k8s.io/v1beta1
```

**See**: [observability.md](observability.md) for autoscaling metrics.
