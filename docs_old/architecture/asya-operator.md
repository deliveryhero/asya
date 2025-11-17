# Asya🎭 Operator

Kubernetes operator for deploying Asya🎭 actors with automatic sidecar injection and KEDA autoscaling.

> **Full Documentation**: [operator/README.md](../../operator/README.md)

## Overview

The operator watches `AsyncActor` CRDs and automatically:
- Creates message queues on the configured transport
- Injects sidecar containers
- Creates workloads (Deployment or StatefulSet)
- Configures KEDA autoscaling
- Manages volumes and environment

## Why Use the Operator?

**Without operator** (manual):
- 100+ lines of YAML
- Manual sidecar configuration
- Complex KEDA setup
- Repetitive boilerplate

**With operator**:
```yaml
# ~20 lines
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  # Actor name is automatically used as the queue name
  transport: rabbitmq
  scaling:
    enabled: true
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-actor:latest
```

## Key Benefits

- Clean declarative API
- Automatic sidecar injection
- Centralized sidecar version management
- Multiple workload kinds (Deployment or StatefulSet)
- Built-in KEDA integration
- Consistent patterns across all actors

## Installation

```bash
# Install CRD
kubectl apply -f src/asya-operator/config/crd/

# Install operator
helm install asya-operator deploy/helm-charts/asya-operator \
  -n asya-system --create-namespace
```

## Basic Example

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello-actor
spec:
  # Actor name is automatically used as the queue name
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    queueLength: 5
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: asya-runtime:latest
```

## Key Concepts

### Reconciliation Behavior

The operator follows a standard Kubernetes controller pattern with event-driven reconciliation:

**Reconciliation triggers**:
- AsyncActor spec changes (user edits, CI/CD updates)
- Owned resource changes (Deployment/StatefulSet updates, deletions)
- Periodic resync (default: every 10 hours)

**Reconciliation filters**:
- KEDA ScaledObject status updates (filtered to reduce event churn)
- AsyncActor status-only updates (filtered by GenerationChangedPredicate)

**Reconciliation flow**:
1. **Validation**: Validate AsyncActor spec and transport configuration
2. **Queue management**: Create/update message queues on configured transport
3. **ServiceAccount**: Create ServiceAccount with IRSA annotations (SQS only, if actorRoleArn configured)
4. **Runtime ConfigMap**: Ensure asya_runtime.py ConfigMap exists in actor namespace
5. **Workload**: Create/update Deployment/StatefulSet with sidecar injection
6. **Pod health check**: Verify pods are healthy and not in failing states
7. **KEDA**: Create/update ScaledObject for autoscaling (if enabled)
8. **HPA status**: Read desired replicas from KEDA-managed HPA (requeue if HPA not found)
9. **Queue metrics**: Update queue depth metrics (optional, non-critical)
10. **Status update**: Update AsyncActor status with conditions, replica counts, and display fields

**Failure handling**:
- Transport validation errors: Mark TransportReady condition as False, stop reconciliation
- Workload creation errors: Mark WorkloadReady condition as False, requeue
- Pod health failures: Mark WorkloadReady condition as False based on pod states
- HPA not found: Requeue after 5 seconds (KEDA may still be creating it)
- SQS queue deletion cooldown: Requeue after 65 seconds (AWS requires 60-second cooldown)

**Status updates**:
- Conditions track readiness of transport, workload, and scaling components
- Replica counts (ready, pending, failing) derived from Deployment status and pod states
- Queue metrics (queued, processing) fetched from transport APIs
- Scaling events (last scale time, direction) tracked for observability

### Queue Management

The operator automatically creates and manages message queues for each AsyncActor:

- Queue name matches the AsyncActor's `metadata.name`
- Queue is created on the transport specified in `spec.transport`
- Queues are configured with appropriate settings (durable, auto-delete, etc.)
- Queue creation happens before workload deployment
- Operator validates transport exists and is enabled before creating queues

Example: An AsyncActor named `my-actor` automatically gets a queue named `my-actor` on the configured transport.

### Workload Types

- **Deployment**: Stateless actors (default)
- **StatefulSet**: Actors needing persistent storage

### Autoscaling

KEDA-based queue depth scaling:
```yaml
scaling:
  minReplicas: 0        # Scale to zero when idle
  maxReplicas: 50
  queueLength: 5        # Messages per replica
```

Behavior:
- 0 messages → 0 replicas (after cooldown)
- 10 messages → 2 replicas (10/5)
- 50 messages → 10 replicas (capped at maxReplicas)

### Status Monitoring

**List actors**:
```bash
kubectl get asyas
```

Output columns:
```
NAME          STATUS    RUNNING   PENDING   FAILING   MIN   MAX   LAST-SCALE   AGE
hello-actor   Running   3         0         0         0     10    5m (up)      2h
error-actor   Degraded  0         0         1         0     10    -            30m
```

**Wide output** (`kubectl get asyas -o wide`):
```
NAME          STATUS    RUNNING   PENDING   FAILING   MIN   MAX   LAST-SCALE   AGE   DESIRED   WORKLOAD    TRANSPORT   SCALING   QUEUED   PROCESSING
hello-actor   Running   3         0         0         0     10    5m (up)      2h    3         Deployment  Ready       KEDA      15       2
```

Column descriptions:
- **STATUS**: Overall actor state (Running, Napping, Degraded, Creating, etc.)
- **RUNNING**: Number of pods that are ready and running
- **PENDING**: Pods created but not ready yet (normal startup, waiting for resources)
- **FAILING**: Pods with init containers or runtime containers in error states actively retrying (CrashLoopBackOff, ImagePullBackOff, etc.)
- **MIN/MAX**: KEDA autoscaling bounds
- **LAST-SCALE**: Time since last scaling event and direction (up/down)
- **DESIRED** (wide): Target replica count from KEDA HPA (may be stale, see Reconciliation Behavior)
- **WORKLOAD** (wide): Deployment or StatefulSet
- **TRANSPORT** (wide): Transport readiness status
- **SCALING** (wide): KEDA (autoscaling) or Manual (fixed replicas)
- **QUEUED** (wide): Messages waiting in queue
- **PROCESSING** (wide): Messages currently being processed

**FAILING vs pod phase**:
- `FAILING=1` means pod is in an error state where Kubernetes keeps retrying with exponential backoff
- Permanently failed pods (phase `Failed`) don't count in FAILING - these have stopped retrying
- Failing states are detected in both init containers and runtime containers
- Common failing reasons:
  - `CrashLoopBackOff` - Container crashes after starting
  - `ImagePullBackOff` / `ErrImagePull` - Cannot pull container image
  - `CreateContainerError` / `CreateContainerConfigError` - Configuration error
  - `RunContainerError` - Container runtime error
  - `InvalidImageName` - Malformed image name

**Detailed status**:
```bash
kubectl get asya hello-actor -o yaml
```

Shows:
- WorkloadReady (Deployment created)
- ScalingReady (KEDA configured)
- References to created resources

## Examples

See [examples/asyas/](../../examples/asyas/) for:
- simple-actor.yaml
- statefulset-actor.yaml
- multi-container-actor.yaml
- custom-sidecar-actor.yaml
- no-scaling-actor.yaml

## Full Documentation

For complete details, see:
- [operator/README.md](../../operator/README.md) - Full reference
- [operator/DEVELOPMENT.md](../../operator/DEVELOPMENT.md) - Development guide
- [Troubleshooting](../../operator/README.md#troubleshooting) - Common issues

## AsyncActor CRD API Reference

> **CRD Source**: [`src/asya-operator/config/crd/asya.sh_asyncactors.yaml`](../../src/asya-operator/config/crd/)

### API Version

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
```

### Metadata

Standard Kubernetes metadata:

```yaml
metadata:
  name: my-actor          # Required: Actor name
  namespace: default      # Optional: Namespace (default: default)
  labels:                 # Optional: Labels
    app: my-app
  annotations:            # Optional: Annotations
    description: "My actor"
```

### Spec

#### Required Fields

```yaml
spec:
  # Actor name is automatically used as the queue name
  transport: rabbitmq     # Required: Transport name (configured in operator)
  workload:               # Required: Workload template
    type: Deployment      # Required: Workload type
    template: {...}       # Required: Pod template
```

#### Transport Configuration

The `transport` field references a transport configured at the operator level. Common values:
- `rabbitmq` - RabbitMQ transport
- `sqs` - AWS SQS transport

Transport details (host, credentials, etc.) are configured in the operator's Helm values, not in the AsyncActor CRD.

**Example:**
```yaml
transport: rabbitmq  # References operator-configured transport
```

**Configuring Transports (in operator values.yaml):**
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
    enabled: false
    type: sqs
    config:
      region: us-east-1
      queueBaseURL: ""
```

#### Sidecar Configuration

```yaml
sidecar:
  image: asya-sidecar:latest              # Optional: Sidecar image
  imagePullPolicy: IfNotPresent           # Optional: Pull policy
  resources:                               # Optional: Resource limits
    limits:
      cpu: 500m
      memory: 256Mi
    requests:
      cpu: 100m
      memory: 64Mi
  env:                                     # Optional: Environment variables
  - name: ASYA_RUNTIME_TIMEOUT
    value: "5m"
```

#### Socket Configuration

```yaml
socket:
  path: /tmp/sockets/app.sock  # Optional: Unix socket path
  maxSize: "10485760"          # Optional: Max message size (bytes)
```

#### Timeout Configuration

```yaml
timeout:
  processing: 300              # Optional: Processing timeout (seconds)
  gracefulShutdown: 30         # Optional: Graceful shutdown timeout
```

#### Scaling Configuration

```yaml
scaling:
  enabled: true                # Optional: Enable KEDA autoscaling
  minReplicas: 0               # Optional: Minimum replicas (0 = scale to zero)
  maxReplicas: 10              # Optional: Maximum replicas
  pollingInterval: 10          # Optional: Queue polling interval (seconds)
  cooldownPeriod: 60           # Optional: Cooldown before scale to zero
  queueLength: 5               # Optional: Messages per replica
```

#### Workload Configuration

**Deployment:**
```yaml
workload:
  type: Deployment
  replicas: 1                  # Optional: Initial replicas (ignored if scaling enabled)
  template:                    # Required: Pod template
    metadata:
      labels:
        app: my-app
    spec:
      containers:
      - name: asya-runtime
        image: my-runtime:latest
        env:
        - name: ASYA_HANDLER
          value: "my_module.process"
        resources:
          limits:
            cpu: 1000m
            memory: 1Gi
```

**StatefulSet:**
```yaml
workload:
  type: StatefulSet
  template:
    spec:
      containers:
      - name: asya-runtime
        image: my-stateful-runtime:latest
        volumeMounts:
        - name: data
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

### Status

The operator updates the status with information about created resources:

```yaml
status:
  conditions:
  - type: WorkloadReady
    status: "True"
    reason: WorkloadCreated
    message: Deployment successfully created
    lastTransitionTime: "2024-10-06T12:00:00Z"

  - type: ScalingReady
    status: "True"
    reason: ScaledObjectCreated
    message: KEDA ScaledObject successfully created
    lastTransitionTime: "2024-10-06T12:00:00Z"

  workloadRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-actor
    namespace: default

  scaledObjectRef:
    name: my-actor
    namespace: default

  observedGeneration: 1
```

**Condition Types:**
- `WorkloadReady` - Workload (Deployment or StatefulSet) created successfully
- `ScalingReady` - KEDA ScaledObject created successfully (if scaling enabled)

**Status Reasons:**
- `WorkloadCreated` - Workload created
- `WorkloadFailed` - Workload creation failed
- `ScaledObjectCreated` - ScaledObject created
- `ScaledObjectFailed` - ScaledObject creation failed

### Complete Example

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor
  namespace: production
  labels:
    app: text-processing
    team: nlp
  annotations:
    description: "Text processing actor with GPU support"
spec:
  # Transport (references operator-configured transport)
  transport: rabbitmq

  # Sidecar
  sidecar:
    image: asya-sidecar:v1.2.3
    imagePullPolicy: IfNotPresent
    resources:
      limits:
        cpu: 500m
        memory: 256Mi
      requests:
        cpu: 100m
        memory: 64Mi
    env:
    - name: ASYA_RUNTIME_TIMEOUT
      value: "10m"

  # Socket
  socket:
    path: /tmp/sockets/app.sock
    maxSize: "52428800"  # 50MB

  # Timeout
  timeout:
    processing: 600       # 10 minutes
    gracefulShutdown: 60  # 1 minute

  # Scaling
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 50
    pollingInterval: 10
    cooldownPeriod: 120
    queueLength: 5

  # Workload
  workload:
    type: Deployment
    template:
      metadata:
        labels:
          app: text-processor
          version: v2
      spec:
        containers:
        - name: asya-runtime
          image: my-text-processor:v2.0
          env:
          - name: ASYA_HANDLER
            value: "text_processor.handlers.process_text"
          - name: MODEL_NAME
            value: "bert-large"
          - name: DEVICE
            value: "cuda"
          resources:
            limits:
              nvidia.com/gpu: 1
              cpu: 4000m
              memory: 8Gi
            requests:
              cpu: 2000m
              memory: 4Gi
          volumeMounts:
          - name: models
            mountPath: /models
        volumes:
        - name: models
          persistentVolumeClaim:
            claimName: model-cache
        nodeSelector:
          accelerator: nvidia-tesla-t4
        tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
```

### kubectl Usage

**Create Actor:**
```bash
kubectl apply -f my-actor.yaml
```

**List Actors:**
```bash
# All namespaces
kubectl get asyas -A

# Specific namespace
kubectl get asyas -n production

# With labels
kubectl get asyas -l app=text-processing
```

**Describe Actor:**
```bash
kubectl describe asya my-actor
```

**Get Status:**
```bash
# Full status
kubectl get asya my-actor -o yaml

# Just conditions
kubectl get asya my-actor -o jsonpath='{.status.conditions}'

# Check if ready
kubectl get asya my-actor -o jsonpath='{.status.conditions[?(@.type=="WorkloadReady")].status}'
```

**Update Actor:**
```bash
# Edit interactively
kubectl edit asya my-actor

# Patch
kubectl patch asya my-actor -p '{"spec":{"scaling":{"maxReplicas":100}}}'

# Replace
kubectl replace -f my-actor.yaml
```

**Delete Actor:**
```bash
kubectl delete asya my-actor

# Force delete
kubectl delete asya my-actor --grace-period=0 --force
```

## Next Steps

- [AsyncActor Examples](../guides/examples-actors.md) - Example AsyncActor configurations
- [Gateway Component](asya-gateway.md) - MCP gateway
- [Sidecar Component](asya-sidecar.md) - Message routing
- [Deployment Guide](../guides/deployment.md) - Deployment strategies
