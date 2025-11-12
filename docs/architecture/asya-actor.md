# AsyncActor (CRD)

The AsyncActor Custom Resource Definition (CRD) is the core abstraction for deploying actor workloads in the Asya🎭 framework. It declaratively defines an actor's configuration, including transport, scaling, and workload specifications.

## Status Reference

AsyncActors report a comprehensive status that reflects the current state of the workload, transport, and scaling infrastructure. The status is visible in `kubectl get asyncactor` output and provides detailed diagnostics for troubleshooting.

### Status Fields

The AsyncActor status includes the following fields:

- **Status**: Overall status (see table below)
- **Running**: Number of ready pods
- **Pending**: Number of pods created but not yet ready (includes Pending phase and Running-but-not-ready)
- **Failing**: Number of pods in failing states (CrashLoopBackOff, ImagePullBackOff, etc.)
- **Total**: Total number of non-terminated pods
- **Desired**: Target number of replicas (from HPA if KEDA enabled, or spec.workload.replicas)
- **Last-Scale**: Time since last scaling event with direction (e.g., "5m ago (up)", "2h ago (down)")
- **Transport** (wide output): Transport readiness (Ready/NotReady)
- **Scaling** (wide output): Scaling mode (KEDA/Manual)
- **Queued** (wide output): Number of messages waiting in queue
- **Processing** (wide output): Number of messages currently being processed

### Status Table

The following table describes all possible AsyncActor statuses, their underlying pod conditions, and example scenarios:

| AsyncActor Status | Pod Conditions / Replica State | Example Scenario |
|-------------------|--------------------------------|------------------|
| **Creating** | ObservedGeneration=0, no workload created yet | Initial AsyncActor creation, operator hasn't completed first reconciliation |
| **Running** | Ready=Desired, all pods healthy, no failures | Normal operation: 3/3 pods ready, processing messages |
| **Napping** | Desired=0, KEDA scaling enabled | Scale-to-zero: no messages in queue, KEDA scaled actor to 0 replicas |
| **Degraded** | Ready<Total, state persists >5min, no active scaling | Partial capacity: 2/3 pods ready for extended period, 1 pod stuck pending |
| **ScalingUp** | Total<Desired or Ready<Total (recent) | KEDA scaling up: 2/5 pods ready, 3 more being created |
| **ScalingDown** | Total>Desired | KEDA scaling down: 5/3 pods running, 2 being terminated |
| **Terminating** | DeletionTimestamp set | AsyncActor deletion in progress, cleaning up resources |
| **TransportError** | TransportReady condition=False | RabbitMQ connection failed, SQS queue creation failed, transport credentials invalid |
| **WorkloadError** | WorkloadReady=False, FailingPods>0, Ready<Desired, generic error | Catch-all workload failure: failing pods with no specific classification |
| **PendingResources** | PodScheduled=False + "Insufficient" in message | Insufficient CPU/memory/GPU, no nodes with requested resources available |
| **ImagePullError** | Container waiting: ImagePullBackOff or ErrImagePull | Invalid image name, registry authentication failed, image not found |
| **RuntimeError** | asya-runtime container: CrashLoopBackOff | Python handler crashes, import errors, CUDA OOM, unhandled exceptions |
| **SidecarError** | asya-sidecar container: CrashLoopBackOff | Sidecar crashes, transport connection failures, envelope routing errors |
| **VolumeError** | Pod events: MountVolume or VolumeMount failures | PVC not bound, volume provisioning failed, mount path conflicts |
| **ConfigError** | Pod events: ConfigMap or Secret not found | Missing ASYA_HANDLER env var, missing transport credentials, runtime ConfigMap missing |
| **ScalingError** | ScalingReady=False (KEDA enabled) | ScaledObject creation failed, KEDA controller unavailable, HPA errors |

### Status Priority Logic

Statuses are determined using the following priority order (highest to lowest):

1. **Lifecycle states**: Terminating (DeletionTimestamp), Creating (ObservedGeneration=0)
2. **Critical errors**: TransportError, WorkloadError variants (PendingResources, ImagePullError, RuntimeError, SidecarError, VolumeError, ConfigError), ScalingError
3. **Transitional states**: Napping (Desired=0 + KEDA), ScalingUp (Total<Desired or Ready<Total), ScalingDown (Total>Desired)
4. **Operational states**: Running (Ready=Desired), Degraded (Ready<Total for >5min)

### Error Classification Details

**WorkloadError variants** are classified by examining the WorkloadReady condition message:

- **PendingResources**: Message contains "Insufficient" (CPU, memory, GPU, storage)
- **ImagePullError**: Message contains "ImagePullBackOff" or "ErrImagePull"
- **RuntimeError**: Message contains "asya-runtime" and "CrashLoopBackOff"
- **SidecarError**: Message contains "asya-sidecar" and "CrashLoopBackOff"
- **VolumeError**: Message contains "MountVolume" or "VolumeMount"
- **ConfigError**: Message contains "configmap" or "secret" with "not found"
- **WorkloadError**: Generic fallback for unclassified workload failures

**Failing pod detection** includes:

- Container restart count > 5
- Container waiting reasons: CrashLoopBackOff, ImagePullBackOff, ErrImagePull, CreateContainerError, CreateContainerConfigError, InvalidImageName, RunContainerError
- Pod conditions: PodScheduled=False with Reason=Unschedulable
- Pod phase: Failed

## Spec Reference

See [AsyncActor CRD definition](../../src/asya-operator/api/v1alpha1/asya_types.go) for complete spec schema.

### Key Spec Fields

- **transport**: Transport name (references operator-configured transport)
- **sidecar**: Sidecar container configuration (image, resources, env vars)
- **timeout**: Processing and graceful shutdown timeouts
- **scaling**: KEDA autoscaling configuration (minReplicas, maxReplicas, queueLength, advanced options)
- **workload**: Workload template (kind: Deployment/StatefulSet, replicas, pod template)

### Example AsyncActor

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor
  namespace: default
spec:
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    queueLength: 5
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
          env:
          - name: ASYA_HANDLER
            value: my_module.process
          - name: ASYA_HANDLER_MODE
            value: payload
```

## Related Documentation

- [Operator](asya-operator.md) - AsyncActor reconciliation and management
- [Sidecar](asya-sidecar.md) - Envelope routing and transport integration
- [Runtime](asya-runtime.md) - Actor handler execution
- [KEDA](scaling-keda.md) - Autoscaling configuration
- [Transport](transport.md) - Transport configuration and management
