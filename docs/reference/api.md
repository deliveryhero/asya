# API Reference

AsyncActor CRD API specification.

> 📄 **CRD Source**: [`operator/config/crd/asya.io_asyas.yaml`](../../operator/config/crd/)
> 📖 **Operator README**: [`operator/README.md`](../../operator/README.md)

## Asya Resource

### API Version

```yaml
apiVersion: asya.io/v1alpha1
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
  queueName: my-queue     # Required: Queue name to consume from

  transport:              # Required: Transport configuration
    type: rabbitmq        # Required: Transport type

  workload:               # Required: Workload template
    type: Deployment      # Required: Workload type
    template: {...}       # Required: Pod template
```

#### Transport Configuration

**RabbitMQ:**
```yaml
transport:
  type: rabbitmq
  rabbitmq:
    host: rabbitmq.default.svc.cluster.local  # Required
    port: 5672                                 # Required
    username: admin                            # Required
    passwordSecretRef:                         # Required
      name: rabbitmq-secret
      key: password
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
      - name: runtime
        image: my-runtime:latest
        env:
        - name: ASYA_PROCESS_MODULE
          value: "my_module:process"
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
      - name: runtime
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

**Job:**
```yaml
workload:
  type: Job
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: runtime
        image: my-batch-processor:latest
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
- `WorkloadReady` - Workload (Deployment/StatefulSet/Job) created successfully
- `ScalingReady` - KEDA ScaledObject created successfully (if scaling enabled)

**Status Reasons:**
- `WorkloadCreated` - Workload created
- `WorkloadFailed` - Workload creation failed
- `ScaledObjectCreated` - ScaledObject created
- `ScaledObjectFailed` - ScaledObject creation failed

## Complete Example

```yaml
apiVersion: asya.io/v1alpha1
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
  # Queue configuration
  queueName: text-processing-queue

  # Transport
  transport:
    type: rabbitmq
    rabbitmq:
      host: rabbitmq.infrastructure.svc.cluster.local
      port: 5672
      username: processor
      passwordSecretRef:
        name: rabbitmq-processor-creds
        key: password

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
    - name: ASYA_STEP_HAPPY_END
      value: "text-processing-complete"
    - name: ASYA_STEP_ERROR_END
      value: "text-processing-errors"

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
        - name: runtime
          image: my-text-processor:v2.0
          env:
          - name: ASYA_PROCESS_MODULE
            value: "text_processor.handlers:process_text"
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

## kubectl Usage

### Create Actor

```bash
kubectl apply -f my-actor.yaml
```

### List Actors

```bash
# All namespaces
kubectl get asyas -A

# Specific namespace
kubectl get asyas -n production

# With labels
kubectl get asyas -l app=text-processing
```

### Describe Actor

```bash
kubectl describe asya my-actor
```

### Get Status

```bash
# Full status
kubectl get asya my-actor -o yaml

# Just conditions
kubectl get asya my-actor -o jsonpath='{.status.conditions}'

# Check if ready
kubectl get asya my-actor -o jsonpath='{.status.conditions[?(@.type=="WorkloadReady")].status}'
```

### Update Actor

```bash
# Edit interactively
kubectl edit asya my-actor

# Patch
kubectl patch asya my-actor -p '{"spec":{"scaling":{"maxReplicas":100}}}'

# Replace
kubectl replace -f my-actor.yaml
```

### Delete Actor

```bash
kubectl delete asya my-actor

# Force delete
kubectl delete asya my-actor --grace-period=0 --force
```

## Next Steps

- [Operator Component](../components/operator.md) - Operator details
- [Example Actors](../examples/actors.md) - Example configurations
- [Deployment Guide](../guides/deployment.md) - Deploy actors
