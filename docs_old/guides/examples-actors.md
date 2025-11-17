# Actor Examples

Progressive examples from minimal to advanced configurations.

> **Example files:** [`examples/asyas/`](../../examples/asyas/)
> **See also:** [Examples README](../../examples/asyas/README.md) for quick reference

## Minimal Actor

> **Example file:** [`simple-actor.yaml`](../../examples/asyas/simple-actor.yaml)

The simplest possible actor (without autoscaling):

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: echo-actor
spec:
  transport: rabbitmq
  workload:
    kind: Deployment
    template:
      spec:  # Regular Deployment spec format
        containers:
        - name: asya-runtime
          image: asya-runtime:latest
          # NOTE: don't specify 'command' - asya-operator will inject entrypoint /opt/asya/asya_runtime.py and set command to call it
          env:
          - name: ASYA_HANDLER  # the only required env var for asya_runtime.py
            value: "echo_handler.process"
        # NOTE: asya-operator will inject container `asya-sidecar` - you're free to have as many other containers as you want, as long as they are not called asya-sidecar
```

This creates:
- A queue named `echo-actor` (matches metadata.name)
- A Deployment with asya-sidecar automatically injected
- **1 fixed replica** (no autoscaling by default)

Defaults applied:
- `workload.replicas: 1`
- `scaling.enabled: false`
- `timeout.processing: 300` (5 minutes)
- `socket.path: /tmp/sockets/app.sock`

## Add Autoscaling

> **Example file:** [`simple-actor.yaml`](../../examples/asyas/simple-actor.yaml) (with `scaling` section)

Enable KEDA autoscaling based on queue depth:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: echo-actor
spec:
  transport: rabbitmq  # or: sqs

  scaling:             # New: enable KEDA autoscaling
    enabled: true
    minReplicas: 0     # Scale to zero when idle
    maxReplicas: 10
    queueLength: 5     # Target new pod per each 5 messages in the queue

  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: asya-runtime:latest
          env:
          - name: ASYA_HANDLER
            value: "echo_handler.process"
```

> **What changed:**
> - `scaling.enabled: true` - activates KEDA autoscaling
> - `minReplicas: 0` - scale to zero when queue is empty (cost savings)
> - `maxReplicas: 10` - cap at 10 pods maximum (default is 50)
> - `queueLength: 5` - maintain ~5 messages per pod (default is also 5)

Additional defaults when scaling is enabled:
- `pollingInterval: 10` seconds - how often KEDA checks the queue
- `cooldownPeriod: 60` seconds - wait time before scaling down

The operator creates a ScaledObject that monitors queue depth and scales the Deployment accordingly.

## Add Resource Limits

> **Example file:** [`simple-actor.yaml`](../../examples/asyas/simple-actor.yaml) (includes resource limits)

Set CPU/memory limits for predictable performance:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: echo-actor
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
          image: asya-runtime:latest
          env:
          - name: ASYA_HANDLER
            value: "echo_handler.process"
          resources:    # New: resource limits
            requests:
              cpu: 500m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1Gi
```

> **What changed:**
> - Added `resources` to the runtime container
> - `requests` = minimum guaranteed resources
> - `limits` = maximum allowed usage (pod gets throttled/OOMKilled if exceeded)

## GPU Actor

> **Example file:** [`gpu-actor.yaml`](../../examples/asyas/gpu-actor.yaml)

Add GPU for AI inference:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: llm-actor
spec:
  transport: rabbitmq

  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 5
    queueLength: 2              # Lower for expensive GPU workloads

  timeout:                      # New: longer timeout for model loading
    processing: 600             # 10 minutes

  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-llm-server:latest
          env:
          - name: ASYA_HANDLER
            value: "model_server.inference"
          resources:
            requests:
              cpu: 2000m
              memory: 8Gi
            limits:
              nvidia.com/gpu: 1  # New: request 1 GPU
              cpu: 4000m
              memory: 16Gi
        nodeSelector:            # New: schedule only on GPU nodes
          accelerator: nvidia-tesla-t4
        tolerations:             # New: tolerate GPU taints
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
```

> **What changed:**
> - `queueLength: 2` - lower target for expensive GPU processing
> - `timeout.processing: 600` - allows 10min for model initialization + inference
> - `nvidia.com/gpu: 1` - requests 1 GPU from Kubernetes
> - `nodeSelector` - ensures scheduling on GPU-enabled nodes
> - `tolerations` - allows scheduling on tainted GPU nodes

## Multi-Container Pod

> **Example file:** [`multi-container-actor.yaml`](../../examples/asyas/multi-container-actor.yaml)

Add a Redis sidecar for caching:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: cached-actor
spec:
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
          image: my-app:latest
          env:
          - name: ASYA_HANDLER
            value: "processor.process"
          - name: CACHE_HOST        # New: point to localhost Redis
            value: localhost
          - name: CACHE_PORT
            value: "6379"
        - name: redis               # New: add Redis container
          image: redis:7-alpine
          ports:
          - containerPort: 6379
```

> **What changed:**
> - Added `redis` container alongside `runtime`
> - Both containers share the pod network (communicate via `localhost`)
> - Useful for local caching, proxies, or helper services

## Advanced Scaling Configuration

> **Example file:** [`advanced-scaling-actor.yaml`](../../examples/asyas/advanced-scaling-actor.yaml)

Use advanced KEDA scaling features with custom formulas:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: advanced-scaling-actor
spec:
  transport: rabbitmq

  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 50
    pollingInterval: 10
    cooldownPeriod: 60
    queueLength: 10

    advanced:                    # New: Advanced KEDA configuration
      formula: "ceil(queueLength / 10)"
      target: "10"
      activationTarget: "5"
      metricType: "AverageValue"
      restoreToOriginalReplicaCount: false

  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
          env:
          - name: ASYA_HANDLER
            value: "handlers.process"
```

> **What changed:**
> - `scaling.advanced.formula` - Custom scaling calculation using queue metrics
> - `scaling.advanced.target` - Target value for the metric
> - `scaling.advanced.activationTarget` - Threshold to scale from 0 to 1
> - `scaling.advanced.metricType` - How KEDA interprets the metric (AverageValue, Value, Utilization)

## Custom Python Configuration

> **Example file:** [`custom-python-actor.yaml`](../../examples/asyas/custom-python-actor.yaml)

Use custom Python executable paths for Conda or other environments:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: conda-ml-actor
spec:
  transport: rabbitmq

  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 5

  workload:
    kind: Deployment
    pythonExecutable: "/opt/conda/bin/python"  # New: Custom Python path

    template:
      spec:
        containers:
        - name: asya-runtime
          image: continuumio/miniconda3:latest
          env:
          - name: PYTHONPATH             # Configure import path
            value: "/app/handlers"
          - name: ASYA_HANDLER
            value: "ml_model.predict"
          - name: MODEL_PATH
            value: "/models/my-model"
```

> **What changed:**
> - `workload.pythonExecutable` - Path to Python executable (defaults to `python3`)
> - `PYTHONPATH` - Configure module import paths for handler resolution

> **Use case:** Conda environments, pyenv, custom Python installations

## Custom Sidecar Configuration

> **Example file:** [`custom-sidecar-actor.yaml`](../../examples/asyas/custom-sidecar-actor.yaml)

Customize the asya-sidecar for high-throughput scenarios:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: high-throughput-actor
spec:
  transport: rabbitmq

  sidecar:                       # New: customize the injected sidecar
    image: asya-sidecar:v2.0
    imagePullPolicy: Always
    resources:
      requests:
        cpu: 200m
        memory: 128Mi
      limits:
        cpu: 1000m
        memory: 512Mi
    env:
    - name: ASYA_RUNTIME_TIMEOUT
      value: "15m"
    - name: ASYA_RABBITMQ_PREFETCH  # New: fetch multiple messages at once
      value: "10"

  timeout:
    processing: 900              # Match sidecar timeout
    gracefulShutdown: 60

  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-processor:latest
          env:
          - name: ASYA_HANDLER
            value: "batch_processor.process"
```

> **What changed:**
> - `sidecar` section configures the automatically injected asya-sidecar container
> - `ASYA_RABBITMQ_PREFETCH: "10"` - fetch 10 messages at once (higher throughput)
> - `timeout.processing: 900` - allow 15min for slow batch processing
> - `sidecar.resources` - allocate more CPU/memory for message routing

## Runtime Configuration (All Environment Variables)

> **Example file:** [`fully-configured-actor.yaml`](../../examples/asyas/fully-configured-actor.yaml)

Configure all available runtime environment variables:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: fully-configured-actor
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
          image: my-custom-runtime:latest
          env:
          # Handler configuration (REQUIRED)
          - name: ASYA_HANDLER
            value: "my_module.MyClass.process"

          # Handler mode (optional, default: "payload")
          - name: ASYA_HANDLER_MODE
            value: "payload"              # "payload" or "envelope"

          # Logging configuration (optional, default: "INFO")
          - name: ASYA_LOG_LEVEL
            value: "DEBUG"                # DEBUG, INFO, WARNING, ERROR, CRITICAL

          # Socket configuration (optional defaults shown)
          - name: ASYA_SOCKET_PATH
            value: "/tmp/sockets/app.sock"

          - name: ASYA_SOCKET_CHMOD
            value: "0o666"                # Socket file permissions

          - name: ASYA_CHUNK_SIZE
            value: "65536"                # Socket read chunk size in bytes

          # Validation (optional, default: "true")
          - name: ASYA_ENABLE_VALIDATION
            value: "true"                 # Validate envelope structure
```

> **Environment variable reference:**
>
> **Required:**
> - `ASYA_HANDLER` - Handler path in format `module.function` or `module.Class.method`
>
> **Handler mode:**
> - `ASYA_HANDLER_MODE: "payload"` (default) - Handler receives only payload, headers/route preserved
> - `ASYA_HANDLER_MODE: "envelope"` - Handler receives full envelope `{id, route, headers, payload}`
>
> **Logging:**
> - `ASYA_LOG_LEVEL` - Set to `DEBUG` for verbose logging, `ERROR` for quiet operation
>
> **Socket tuning:**
> - `ASYA_SOCKET_PATH` - Unix socket path (must match sidecar configuration)
> - `ASYA_SOCKET_CHMOD` - Socket permissions (octal string like `"0o666"`)
> - `ASYA_CHUNK_SIZE` - Buffer size for socket reads (increase for large payloads)
>
> **Validation:**
> - `ASYA_ENABLE_VALIDATION: "false"` - Disable envelope validation (not recommended)

## Multi-Actor Pipeline

> **Example files:** [`pipeline-preprocess.yaml`](../../examples/asyas/pipeline-preprocess.yaml), [`pipeline-inference.yaml`](../../examples/asyas/pipeline-inference.yaml), [`pipeline-postprocess.yaml`](../../examples/asyas/pipeline-postprocess.yaml)

Build a 3-stage AI inference pipeline:

```yaml
# Stage 1: Text preprocessing (CPU-bound, fast)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: preprocess
spec:
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 20           # High parallelism for fast CPU work
    queueLength: 10
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: text-preprocessor:latest
          env:
          - name: ASYA_HANDLER
            value: "preprocessor.clean_text"
---
# Stage 2: Model inference (GPU-bound, slow)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: inference
spec:
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 5            # Limited by GPU availability
    queueLength: 2
  timeout:
    processing: 300           # 5min for model loading
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: bert-inference:latest
          env:
          - name: ASYA_HANDLER
            value: "model.predict"
          resources:
            limits:
              nvidia.com/gpu: 1
---
# Stage 3: Formatting results (CPU-bound, fast)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: postprocess
spec:
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 20           # High parallelism again
    queueLength: 10
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: result-formatter:latest
          env:
          - name: ASYA_HANDLER
            value: "formatter.format_output"
```

> **Pipeline flow:**
> ```
> Client sends envelope with route: ["preprocess", "inference", "postprocess"]
>   → preprocess actor processes, routes to inference queue
>   → inference actor processes, routes to postprocess queue
>   → postprocess actor processes, routes to happy-end (automatic)
>   → happy-end persists result to S3, notifies gateway
> ```

> **Key insight:** Each stage scales independently based on its own queue depth and performance characteristics.

---

## Quick Reference

### Queue Length Guidelines

Tune `queueLength` based on processing speed:

- **Fast (<1s)**: `queueLength: 10-20`
- **Medium (1-10s)**: `queueLength: 5-10`
- **Slow (>10s)**: `queueLength: 1-2`
- **GPU**: `queueLength: 1-2`

### Common Patterns

**Fixed replicas (no autoscaling):**
> **Example file:** [`no-scaling-actor.yaml`](../../examples/asyas/no-scaling-actor.yaml)

```yaml
scaling:
  enabled: false
workload:
  replicas: 3
```

**Labels for organization:**
```yaml
metadata:
  labels:
    team: ml-platform
    environment: production
  annotations:
    owner: "team@example.com"
```

## Next Steps

- [Deployment Examples](deployments.md) - Full deployment examples
- [AsyncActor CRD API](../reference/asya-operator.md#asyncactor-crd-api-reference) - AsyncActor CRD specification
- [Deployment Guide](../guides/deploy.md) - Deploy actors
