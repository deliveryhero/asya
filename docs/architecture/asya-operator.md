# Asya Operator

## Responsibilities

- Watch AsyncActor CRDs
- Inject sidecars into actor pods
- Create Kubernetes Deployments/StatefulSets
- Configure KEDA ScaledObjects for autoscaling
- Create and manage message queues
- Monitor actor health

## How It Works

Operator reconciles AsyncActor CRDs, ensuring actual cluster state matches desired state defined in CRD.

**Reconciliation loop**:
1. Watch for AsyncActor create/update/delete events
2. Validate CRD spec
3. Create/update owned resources (Deployment, ScaledObject, queues)
4. Inject sidecar container and infrastructure components
5. Update AsyncActor status

## Deployment

Deployed in central namespace `asya-system`:

```bash
# Install CRDs
kubectl apply -f src/asya-operator/config/crd/

# Install operator
helm install asya-operator deploy/helm-charts/asya-operator/
```

**Operator watches** all namespaces for AsyncActor resources.

## Resource Ownership

Operator creates and owns:
- **Deployment/StatefulSet**: Actor workload
- **ScaledObject**: KEDA autoscaling configuration
- **Queues**: Message queues (`asya-{actor-name}`)

All owned resources have `ownerReferences` set to AsyncActor—deleting AsyncActor cascades to owned resources.

## Queue Management

Operator automatically creates queues when AsyncActor is created:

**Queue naming**: `asya-{actor_name}`

**Lifecycle**:
- Created when AsyncActor reconciled
- Deleted when AsyncActor deleted
- Not modified when AsyncActor updated

**Transport-specific**:
- **SQS**: Creates queue via AWS SDK
- **RabbitMQ**: Creates queue via RabbitMQ API

## KEDA Integration

Operator creates KEDA ScaledObject for each AsyncActor:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: text-processor
spec:
  scaleTargetRef:
    name: text-processor
  minReplicaCount: 0
  maxReplicaCount: 50
  triggers:
  - type: aws-sqs-queue
    metadata:
      queueURL: https://sqs.us-east-1.amazonaws.com/.../asya-text-processor
      queueLength: "5"
      awsRegion: us-east-1
```

KEDA monitors queue depth, scales Deployment from 0 to maxReplicas.

**See**: [autoscaling.md](autoscaling.md) for details.

## Behavior on Events

### AsyncActor Created

1. Validate spec (transport exists, valid scaling config)
2. Create queue (`asya-{actor-name}`)
3. Create Deployment with injected sidecar
4. Create ScaledObject for autoscaling
5. Update AsyncActor status to `Running`

### AsyncActor Updated

1. Reconcile Deployment (update container images, env, resources)
2. Update ScaledObject if scaling config changed
3. Do NOT modify queue (preserve messages)

### AsyncActor Deleted

1. Delete owned resources (Deployment, ScaledObject)
2. Delete queue
3. Remove finalizers

### Deployment Deleted Manually

Operator recreates Deployment (reconciliation ensures desired state).

### Queue Deleted Manually

Operator recreates queue.

### Queue Modified Manually

Operator ignores (does not reconcile queue content/config).

### Actor Pod Crashes

Kubernetes restarts pod (operator not involved).

## Observability

**Metrics**:
- `asya_operator_reconcile_total`
- `asya_operator_reconcile_errors_total`
- `asya_operator_reconcile_duration_seconds`

**Logs**: Structured logging with reconciliation events.

**See**: [observability.md](observability.md) for complete metrics.

## Configuration

Operator configured via Helm values:

```yaml
transports:
  rabbitmq:
    enabled: true
    type: rabbitmq
    config:
      host: rabbitmq.default.svc.cluster.local
      port: 5672
      username: guest
      passwordSecretRef:
        name: rabbitmq-secret
        key: password
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
```

**AsyncActor references transport by name**:
```yaml
spec:
  transport: sqs
```

Operator validates referenced transport exists.

## Deployment Helm Charts

**See**: [../install/helm-charts.md](../install/helm-charts.md) for operator chart details.
