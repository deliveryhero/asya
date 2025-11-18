# Asya Operator

## Responsibilities

- Watch AsyncActor CRDs across all namespaces
- Validate AsyncActor specs (transport exists, container naming, runtime container requirements)
- Inject sidecar container into actor pods
- Create and manage Kubernetes workloads (Deployment/StatefulSet)
- Configure KEDA ScaledObjects for autoscaling
- Create and manage message queues via transport layer
- Create and manage runtime ConfigMap (`asya-runtime`) containing `asya_runtime.py`
- Create ServiceAccounts with IRSA annotations (for SQS with EKS)
- Monitor actor health and update status with granular error states
- Track replica scaling events and queue metrics

## How It Works

Operator reconciles AsyncActor CRDs, ensuring actual cluster state matches desired state defined in CRD.

**Reconciliation loop**:
1. Watch for AsyncActor create/update/delete events across all namespaces
2. Add finalizer if not present
3. Handle deletion if `deletionTimestamp` is set (delete ScaledObject, delete queue, remove finalizer)
4. Validate AsyncActor spec:
   - No user containers named `asya-sidecar` (reserved)
   - Exactly one container named `asya-runtime` (required)
   - Runtime container must not override `command` (managed by operator)
5. Validate transport exists and is enabled in operator configuration
6. Reconcile transport-specific resources (queue creation via transport layer)
7. Reconcile ServiceAccount with IRSA annotation (SQS only, if `actorRoleArn` configured)
8. Reconcile runtime ConfigMap (`asya-runtime`) in actor's namespace
9. Reconcile workload (Deployment/StatefulSet) with injected sidecar
10. Check pod health and update WorkloadReady condition
11. Reconcile KEDA ScaledObject (if `spec.scaling.enabled=true`)
12. Fetch desired replicas from HPA (if KEDA enabled)
13. Update queue metrics (optional, non-critical)
14. Update status display fields (status, replicas, scaling mode, last scale time)
15. Persist status update

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

Operator creates and owns (via `ownerReferences`):

- **Deployment/StatefulSet**: Actor workload with injected sidecar
- **ScaledObject**: KEDA autoscaling configuration (when `spec.scaling.enabled=true`)
- **TriggerAuthentication**: KEDA auth for queue metrics (transport-specific)
- **ConfigMap**: Runtime script (`asya-runtime`) in actor's namespace
- **ServiceAccount**: IRSA-annotated ServiceAccount (SQS with EKS only)

**Note**: Queues are NOT owned resources. Queues are managed by transport layer but have independent lifecycle (survive AsyncActor deletion by default, deleted explicitly during reconciliation).

Deleting AsyncActor triggers cascade deletion of owned resources via `ownerReferences`.

## Queue Management

Operator automatically creates queues via transport layer abstraction.

**Queue naming**: `asya-{actor_name}`

**Lifecycle**:

- Created when AsyncActor first reconciled (if `spec.scaling.enabled=false`, queue created immediately; if KEDA enabled, KEDA creates queue)
- Deleted when AsyncActor deleted (via finalizer cleanup)
- Preserved when AsyncActor updated (no modification during reconciliation)

**SQS-specific**:

- Queue creation via AWS SDK (`CreateQueue` API)
- Handles 60-second cooldown after deletion (requeues reconciliation after 65 seconds)
- Supports IRSA (IAM Roles for Service Accounts) on EKS
- Supports static credentials via Kubernetes Secrets
- Visibility timeout auto-calculated as 2x `ASYA_RUNTIME_TIMEOUT` if not specified

**RabbitMQ-specific**:

- Queue creation via RabbitMQ Management API
- Queue properties: durable, non-auto-delete
- Supports basic auth via Kubernetes Secrets

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

1. Add finalizer `asya.sh/finalizer`
2. Validate spec (container naming, transport exists)
3. Set `TransportReady` condition
4. Reconcile queue via transport layer (`asya-{actor_name}`)
5. Reconcile ServiceAccount if SQS + IRSA (`asya-{actor_name}` SA with IAM role annotation)
6. Reconcile runtime ConfigMap (`asya-runtime` in actor's namespace)
7. Create Deployment/StatefulSet with injected sidecar + runtime script mount
8. Check pod health, set `WorkloadReady` condition
9. Create ScaledObject if `spec.scaling.enabled=true`, set `ScalingReady` condition
10. Fetch HPA desired replicas (if KEDA enabled)
11. Update queue metrics (queued messages, processing messages)
12. Calculate and set status (Running, Creating, errors)
13. Update status with replicas, scaling mode, last scale time

### AsyncActor Updated

1. Validate spec (same as create)
2. Update runtime ConfigMap if content changed
3. Update Deployment/StatefulSet (images, env, resources, sidecar config)
4. Update or delete ScaledObject based on `spec.scaling.enabled`
5. Do NOT modify queue (preserve messages)
6. Update status fields

### AsyncActor Deleted

1. Delete ScaledObject and TriggerAuthentication
2. Delete queue via transport layer
3. Remove finalizer `asya.sh/finalizer`
4. Kubernetes cascades deletion of Deployment, ConfigMap, ServiceAccount (via `ownerReferences`)

### Deployment Deleted Manually

Operator recreates Deployment on next reconciliation (desired state enforcement).

### Queue Deleted Manually

Operator recreates queue on next reconciliation.

**SQS caveat**: If queue deleted recently, AWS enforces 60-second cooldown. Operator detects `QueueDeletedRecently` error and requeues after 65 seconds.

### Pod Crashes

Kubernetes restarts pod automatically. Operator updates status to reflect pod health:

- **`CrashLoopBackOff` in runtime container**: Status → `RuntimeError`
- **`CrashLoopBackOff` in sidecar container**: Status → `SidecarError`
- **`ImagePullBackOff`**: Status → `ImagePullError`
- **Volume mount failures**: Status → `VolumeError`
- **ConfigMap/Secret not found**: Status → `ConfigError`

Operator is NOT involved in pod restart logic (Kubernetes handles it).

## AsyncActor Status

The operator calculates granular status based on conditions and pod health.

### Status Values

**Operational**:

- `Running` - All conditions ready, pods healthy
- `Napping` - KEDA scaled to zero (no work, intentional)
- `Degraded` - Some replicas unhealthy but not completely failed

**Transitional**:

- `Creating` - First reconciliation (ObservedGeneration=0)
- `ScalingUp` - Replicas increasing
- `ScalingDown` - Replicas decreasing
- `Updating` - Workload being updated
- `Terminating` - DeletionTimestamp set

**Errors**:

- `TransportError` - Transport not ready or queue creation failed
- `ScalingError` - KEDA ScaledObject creation failed
- `WorkloadError` - Generic workload error
- `PendingResources` - Insufficient CPU/memory (Unschedulable pods)
- `ImagePullError` - ImagePullBackOff or ErrImagePull
- `RuntimeError` - Runtime container CrashLoopBackOff
- `SidecarError` - Sidecar container CrashLoopBackOff
- `VolumeError` - Volume mount failures
- `ConfigError` - ConfigMap/Secret not found

### Status Conditions

Operator maintains three conditions:

- `TransportReady` - Transport validated and queue reconciled
- `WorkloadReady` - Workload created and pods healthy
- `ScalingReady` - KEDA ScaledObject created (only if `spec.scaling.enabled=true`)

### kubectl Output

**Standard columns**:

- `STATUS` - Overall status (from status values above)
- `RUNNING` - Ready replicas count
- `FAILING` - Pods in CrashLoopBackOff/ImagePullBackOff
- `TOTAL` - Total non-terminated pods
- `DESIRED` - Target replicas (from HPA or spec)
- `MIN` - Minimum replicas (from spec)
- `MAX` - Maximum replicas (from spec)
- `LAST-SCALE` - Time since last scale event with direction

**Wide columns** (`kubectl get asya -o wide`):

- `WORKLOAD` - Deployment or StatefulSet
- `TRANSPORT` - Ready or NotReady
- `SCALING` - KEDA or Manual
- `QUEUED` - Messages in queue
- `PROCESSING` - In-flight messages

## Validation Rules

Operator enforces strict validation on AsyncActor spec:

### Container Naming

✅ **Required**:

- Exactly one container named `asya-runtime`

❌ **Forbidden**:

- User containers named `asya-sidecar` (reserved for injected sidecar)
- Init containers named `asya-sidecar` (reserved)
- Multiple containers named `asya-runtime`
- Zero containers named `asya-runtime`

### Runtime Container Restrictions

❌ **Forbidden**:

- Overriding `command` field in `asya-runtime` container (operator manages entrypoint)

✅ **Allowed**:

- Custom image (must contain user handler code)
- Custom environment variables (merged with operator-injected vars)
- Custom resource requests/limits
- Custom volume mounts

### Transport Validation

Operator validates that referenced transport exists and is enabled in operator configuration:

```yaml
spec:
  transport: sqs  # Must exist in operator's transports config
```

If transport not found or disabled, reconciliation fails with `TransportError` status.

## Runtime ConfigMap Injection

Operator creates `asya-runtime` ConfigMap in actor's namespace containing `asya_runtime.py`.

**ConfigMap structure**:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: asya-runtime
  namespace: <actor-namespace>
data:
  asya_runtime.py: |
    <runtime script content>
```

**Mount into pods**:
```yaml
volumeMounts:

- name: asya-runtime
  mountPath: /opt/asya/asya_runtime.py
  subPath: asya_runtime.py
  readOnly: true
```

**Runtime script source**:

- Default: `/runtime/asya_runtime.py` (embedded in operator image)
- Override via operator env: `ASYA_RUNTIME_SCRIPT_PATH`

**Update behavior**: ConfigMap updated if content differs from source file.

## Sidecar Injection

Operator injects `asya-sidecar` container into every actor pod.

**Sidecar image**:

- Default: `asya-sidecar:latest`
- Override via operator env: `ASYA_SIDECAR_IMAGE`
- Override per-actor: `spec.sidecar.image`

**Injected environment variables**:

- `ASYA_ACTOR_NAME` - Actor name (for queue naming)
- `ASYA_TRANSPORT` - Transport type (sqs, rabbitmq)
- `ASYA_GATEWAY_URL` - Gateway URL (if configured)
- `ASYA_IS_END_ACTOR` - Set to `true` for `happy-end` and `error-end` actors
- Transport-specific variables (AWS region, RabbitMQ host, etc.)

**Shared volumes**:

- `socket-dir` - Unix socket directory (`/var/run/asya`)
- `tmp` - Temporary directory

## Observability

**Controller metrics** (Prometheus):

- `controller_runtime_reconcile_total{controller="asyncactor"}` - Total reconciliations
- `controller_runtime_reconcile_errors_total{controller="asyncactor"}` - Failed reconciliations
- `controller_runtime_reconcile_time_seconds{controller="asyncactor"}` - Reconciliation duration

**Logs**: Structured logging (JSON format) with reconciliation events, errors, and debug information.

**See**: [observability.md](observability.md) for monitoring setup.

## Configuration

Operator configured via Helm values:

```yaml
transports:
  rabbitmq:
    enabled: false
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
