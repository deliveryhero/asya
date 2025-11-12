# Actor Examples

Progressive AsyncActor examples from minimal to advanced configurations.

> **See also:** [Actor Examples Guide](../../docs/guides/examples-actors.md) for detailed explanations and concepts

## Quick Reference

| Example | Features | Use Case |
|---------|----------|----------|
| [simple-actor.yaml](#1-simple-actoryaml) | Minimal config, RabbitMQ | Getting started |
| [no-scaling-actor.yaml](#2-no-scaling-actoryaml) | Fixed replicas | Predictable load |
| [advanced-scaling-actor.yaml](#3-advanced-scaling-actoryaml) | Custom KEDA formulas | Advanced autoscaling |
| [gpu-actor.yaml](#4-gpu-actoryaml) | GPU resources, node selection | AI inference |
| [fully-configured-actor.yaml](#5-fully-configured-actoryaml) | All runtime env vars | Configuration reference |
| [multi-container-actor.yaml](#6-multi-container-actoryaml) | Redis caching | Multi-container patterns |
| [custom-sidecar-actor.yaml](#7-custom-sidecar-actoryaml) | Sidecar customization | Performance tuning |
| [custom-python-actor.yaml](#8-custom-python-actoryaml) | Custom Python path | Conda/custom environments |
| [pipeline-*.yaml](#9-multi-actor-pipeline) | 3-stage pipeline | Complex workflows |

## Prerequisites

### Required
- Kubernetes 1.23+
- KEDA 2.0+ installed
- Asya🎭 Operator installed
- Transport configured (RabbitMQ or SQS)

### Quick Setup

```bash
# Create transport secret (RabbitMQ example)
kubectl create secret generic rabbitmq-secret \
  --from-literal=password=admin

# Apply an example
kubectl apply -f simple-actor.yaml

# Check status
kubectl get actors
kubectl describe actor hello-actor
```

## Examples

### 1. [simple-actor.yaml](./simple-actor.yaml)

**Minimal configuration** - the simplest possible actor.

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello-actor
spec:
  transport: rabbitmq
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: python:3.13-slim
          env:
          - name: ASYA_HANDLER
            value: "echo_handler.process"
```

**Features:**
- Default autoscaling (0-50 replicas)
- 5-minute processing timeout
- Minimal resource requests

**Use case:** Learning, testing, simple message processing

---

### 2. [no-scaling-actor.yaml](./no-scaling-actor.yaml)

**Fixed replicas** without autoscaling.

**Key differences:**
```yaml
scaling:
  enabled: false
workload:
  replicas: 3  # Fixed number of replicas
```

**Use case:** Predictable load, no autoscaling needed, development

---

### 3. [advanced-scaling-actor.yaml](./advanced-scaling-actor.yaml)

**Advanced KEDA scaling** with custom formulas and thresholds.

**Key features:**
```yaml
scaling:
  enabled: true
  advanced:
    formula: "ceil(queueLength / 10)"
    target: "10"
    activationTarget: "5"
    metricType: "AverageValue"
```

**Use case:** Fine-tuned autoscaling, custom scaling logic

---

### 4. [gpu-actor.yaml](./gpu-actor.yaml)

**GPU workloads** for AI inference.

**Key features:**
```yaml
resources:
  limits:
    nvidia.com/gpu: 1
nodeSelector:
  accelerator: nvidia-tesla-t4
tolerations:
- key: nvidia.com/gpu
  operator: Exists
```

**Use case:** ML inference, GPU-accelerated processing

---

### 5. [fully-configured-actor.yaml](./fully-configured-actor.yaml)

**All runtime environment variables** - complete configuration reference.

**Environment variables:**
- `ASYA_HANDLER` (required) - Handler path
- `ASYA_HANDLER_MODE` - "payload" or "envelope"
- `ASYA_LOG_LEVEL` - Logging verbosity
- `ASYA_SOCKET_PATH` - Unix socket path
- `ASYA_SOCKET_CHMOD` - Socket permissions
- `ASYA_CHUNK_SIZE` - Buffer size
- `ASYA_ENABLE_VALIDATION` - Envelope validation

**Use case:** Configuration reference, advanced setups

---

### 6. [multi-container-actor.yaml](./multi-container-actor.yaml)

**Multiple containers** - Redis caching sidecar.

**Pattern:**
```yaml
containers:
- name: asya-runtime
  env:
  - name: CACHE_HOST
    value: localhost  # Communicate via pod network
- name: redis
  image: redis:7-alpine
```

**Use case:** Caching, helper services, multi-stage processing

---

### 7. [custom-sidecar-actor.yaml](./custom-sidecar-actor.yaml)

**Custom sidecar configuration** - all customization options.

**Features:**
```yaml
sidecar:
  image: asya-sidecar:v2.1.0
  resources: { ... }
  env:
  - name: ASYA_LOG_LEVEL
    value: debug
socket:
  dir: /custom/path
  maxSize: "20971520"
timeout:
  processing: 600
```

**Use case:** Advanced configurations, debugging, performance tuning

---

### 8. [custom-python-actor.yaml](./custom-python-actor.yaml)

**Custom Python executable** - Conda or custom environments.

**Key feature:**
```yaml
workload:
  pythonExecutable: "/opt/conda/bin/python"
  template:
    spec:
      containers:
      - env:
        - name: PYTHONPATH
          value: "/app/handlers"
```

**Use case:** Conda environments, custom Python installations

---

### 9. Multi-Actor Pipeline

**3-stage AI inference pipeline:**

- [pipeline-preprocess.yaml](./pipeline-preprocess.yaml) - Text preprocessing (CPU, fast, 0-20 replicas)
- [pipeline-inference.yaml](./pipeline-inference.yaml) - Model inference (GPU, slow, 0-5 replicas)
- [pipeline-postprocess.yaml](./pipeline-postprocess.yaml) - Result formatting (CPU, fast, 0-20 replicas)

**Deploy all stages:**
```bash
kubectl apply -f pipeline-preprocess.yaml
kubectl apply -f pipeline-inference.yaml
kubectl apply -f pipeline-postprocess.yaml
```

**Send request:**
```json
{
  "id": "req-123",
  "route": {"actors": ["preprocess", "inference", "postprocess"], "current": 0},
  "payload": {"text": "Hello world"}
}
```

**Flow:**
```
preprocess → inference → postprocess → happy-end (automatic)
```

**Use case:** Complex workflows, independent stage scaling

---

## Common Tasks

### Check Actor Status

```bash
# List all actors
kubectl get actors

# Get detailed status
kubectl describe actor <name>

# Check conditions
kubectl get actor <name> -o jsonpath='{.status.conditions}' | jq

# Watch for changes
kubectl get actors -w
```

### Monitor Scaling

```bash
# Watch HPA
kubectl get hpa -w

# Check KEDA metrics
kubectl get scaledobject <actor-name> -o yaml

# Check queue depth (RabbitMQ)
kubectl exec -n rabbitmq rabbitmq-0 -- rabbitmqctl list_queues
```

### Debugging

```bash
# Check operator logs
kubectl logs -n asya-system deploy/asya-operator -f

# Check sidecar logs
kubectl logs <pod-name> -c asya-sidecar

# Check runtime logs
kubectl logs <pod-name> -c asya-runtime

# Check all containers
kubectl logs <pod-name> --all-containers=true
```

### Update an Actor

```bash
# Edit in place
kubectl edit actor <name>

# Or update from file
kubectl apply -f my-actor.yaml

# Check rollout status
kubectl rollout status deployment/<actor-name>
```

### Delete an Actor

```bash
# Delete the Actor (cascades to Deployment and ScaledObject)
kubectl delete actor <name>

# Verify cleanup
kubectl get deployment,scaledobject
```

## Next Steps

- [Actor Examples Guide](../../docs/guides/examples-actors.md) - Detailed explanations and concepts
- [Deployment Guide](../../docs/guides/deploy.md) - Production deployment
- [AsyncActor API Reference](../../docs/reference/asya-operator.md) - Complete CRD specification
