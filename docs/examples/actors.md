# Actor Examples

Example actor configurations demonstrating various patterns.

> 📄 **Examples**: [`examples/asyas/`](../../examples/asyas/)
> 📖 **Examples README**: [`examples/README.md`](../../examples/README.md)

## Simple Actor

Basic actor with RabbitMQ and autoscaling:

```yaml
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: simple-actor
spec:
  queueName: simple-queue

  transport:
    type: rabbitmq
    rabbitmq:
      host: rabbitmq.asya.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-secret
        key: password

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
        - name: runtime
          image: asya-runtime:latest
          env:
          - name: ASYA_PROCESS_MODULE
            value: "echo_handler:process"
```

**Use case:** Basic message processing with auto-scaling

**See:** [`examples/asyas/simple-actor.yaml`](../../examples/asyas/simple-actor.yaml)

## StatefulSet Actor

Actor with persistent storage:

```yaml
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: stateful-actor
spec:
  queueName: stateful-queue

  transport:
    type: rabbitmq
    rabbitmq:
      host: rabbitmq.asya.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-secret
        key: password

  workload:
    type: StatefulSet
    template:
      spec:
        containers:
        - name: runtime
          image: my-stateful-app:latest
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

**Use case:** Actors requiring stable identity or persistent state

**See:** [`examples/asyas/statefulset-actor.yaml`](../../examples/asyas/statefulset-actor.yaml)

## Multi-Container Actor

Actor with additional sidecar containers:

```yaml
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: multi-container-actor
spec:
  queueName: multi-container-queue

  transport:
    type: rabbitmq
    rabbitmq:
      host: rabbitmq.asya.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-secret
        key: password

  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: runtime
          image: my-app:latest
          env:
          - name: CACHE_HOST
            value: localhost
        - name: redis
          image: redis:7-alpine
          ports:
          - containerPort: 6379
```

**Use case:** Actors needing additional services (cache, proxy, etc.)

**See:** [`examples/asyas/multi-container-actor.yaml`](../../examples/asyas/multi-container-actor.yaml)

## Custom Sidecar Configuration

Actor with customized sidecar settings:

```yaml
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: custom-sidecar-actor
spec:
  queueName: custom-sidecar-queue

  transport:
    type: rabbitmq
    rabbitmq:
      host: rabbitmq.asya.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-secret
        key: password

  sidecar:
    image: asya-sidecar:v2.0
    imagePullPolicy: Always
    resources:
      limits:
        cpu: 1000m
        memory: 512Mi
      requests:
        cpu: 200m
        memory: 128Mi
    env:
    - name: ASYA_RUNTIME_TIMEOUT
      value: "15m"
    - name: ASYA_RABBITMQ_PREFETCH
      value: "5"

  timeout:
    processing: 900
    gracefulShutdown: 60

  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: runtime
          image: my-slow-processor:latest
```

**Use case:** Long-running processing, custom timeout, high throughput

**See:** [`examples/asyas/custom-sidecar-actor.yaml`](../../examples/asyas/custom-sidecar-actor.yaml)

## No Scaling Actor

Actor with fixed replica count:

```yaml
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: no-scaling-actor
spec:
  queueName: no-scaling-queue

  transport:
    type: rabbitmq
    rabbitmq:
      host: rabbitmq.asya.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-secret
        key: password

  scaling:
    enabled: false

  workload:
    type: Deployment
    replicas: 3
    template:
      spec:
        containers:
        - name: runtime
          image: my-app:latest
```

**Use case:** Constant processing capacity, no auto-scaling needed

**See:** [`examples/asyas/no-scaling-actor.yaml`](../../examples/asyas/no-scaling-actor.yaml)

## GPU Actor

Actor with GPU support:

```yaml
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: gpu-actor
spec:
  queueName: gpu-inference-queue

  transport:
    type: rabbitmq
    rabbitmq:
      host: rabbitmq.asya.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-secret
        key: password

  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 5
    queueLength: 2  # Lower for GPU workloads

  timeout:
    processing: 600  # 10 minutes for large models

  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: runtime
          image: my-gpu-model:latest
          env:
          - name: ASYA_PROCESS_MODULE
            value: "model_server:inference"
          resources:
            limits:
              nvidia.com/gpu: 1
              cpu: 4000m
              memory: 16Gi
            requests:
              cpu: 2000m
              memory: 8Gi
        nodeSelector:
          accelerator: nvidia-tesla-t4
        tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
```

**Use case:** GPU-accelerated AI inference with cost-efficient scaling

## Pipeline Actor

Actor in a multi-step processing pipeline:

```yaml
# Step 1: Preprocessing
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: preprocess-actor
spec:
  queueName: preprocess
  transport:
    type: rabbitmq
    rabbitmq:
      host: rabbitmq.asya.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-secret
        key: password
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 20
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: runtime
          image: text-preprocessor:latest
---
# Step 2: Inference
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: inference-actor
spec:
  queueName: inference
  transport:
    type: rabbitmq
    rabbitmq:
      host: rabbitmq.asya.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-secret
        key: password
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: runtime
          image: bert-inference:latest
          resources:
            limits:
              nvidia.com/gpu: 1
---
# Step 3: Postprocessing
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: postprocess-actor
spec:
  queueName: postprocess
  transport:
    type: rabbitmq
    rabbitmq:
      host: rabbitmq.asya.svc.cluster.local
      port: 5672
      username: admin
      passwordSecretRef:
        name: rabbitmq-secret
        key: password
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 20
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: runtime
          image: result-formatter:latest
```

**Use case:** Multi-stage AI pipeline with independent scaling per stage

**Message flow:**
```
Client → preprocess → inference → postprocess → happy-end
```

## Best Practices

### Resource Limits

Always set resource limits for predictable scaling:

```yaml
sidecar:
  resources:
    limits:
      cpu: 500m
      memory: 256Mi

workload:
  template:
    spec:
      containers:
      - name: runtime
        resources:
          limits:
            cpu: 2000m
            memory: 2Gi
```

### Queue Length Tuning

Adjust based on processing time:

- **Fast processing (<1s)**: `queueLength: 10-20`
- **Medium processing (1-10s)**: `queueLength: 5-10`
- **Slow processing (>10s)**: `queueLength: 1-2`
- **GPU workloads**: `queueLength: 1-2`

### Labels and Annotations

Use for organization and monitoring:

```yaml
metadata:
  labels:
    app: my-app
    team: data-science
    environment: production
  annotations:
    description: "Text classification actor"
    owner: "team@example.com"
```

## Next Steps

- [Deployment Examples](deployments.md) - Full deployment examples
- [API Reference](../reference/api.md) - Complete API specification
- [Deployment Guide](../guides/deployment.md) - Deploy actors
