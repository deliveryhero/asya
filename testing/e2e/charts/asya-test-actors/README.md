# Asya🎭 Actor Helm Chart

A reusable Helm chart for deploying Asya🎭 AsyncActor resources to Kubernetes.

## Overview

This chart creates an AsyncActor CRD resource. The Asya🎭 operator will automatically handle:
- ✅ Sidecar container injection (asya-sidecar)
- ✅ Runtime command injection (`["python3", "/opt/asya/asya_runtime.py"]`)
- ✅ Socket configuration and volume mounts
- ✅ asya_runtime.py ConfigMap injection

**You only need to configure:**
- Your runtime container (image, env vars, resources)
- Transport reference (configured in operator)
- Scaling parameters (KEDA)

**Python Runtime Requirements:**
- Container image must have `python3` in PATH (or override via `workload.pythonExecutable`)
- Handler function must be importable (set `PYTHONPATH` environment variable)

## Prerequisites

- Kubernetes 1.19+
- Helm 3.x
- AsyncActor CRDs installed (`kubectl apply -f src/asya-operator/config/crd/`)
- Asya🎭 operator running in the cluster
- KEDA installed (if using autoscaling)

## Installation

### Basic Installation

**Note:** This chart is intended for testing purposes only. For production deployments, use bare AsyncActor manifests directly (see `examples/asyas/`).

```bash
helm install my-actor ./testing/e2e/charts/asya-test-actor \
  --set name=my-actor \
  --set transport=rabbitmq \
  --set workload.template.spec.containers[0].env[0].name=ASYA_HANDLER \
  --set workload.template.spec.containers[0].env[0].value="my_module.handler"
```

Note: The actor name (`my-actor`) is automatically used as the queue name.

### Installation with Values File

Create a `my-values.yaml`:

```yaml
name: my-actor
namespace: asya

# Actor name is automatically used as the queue name
# No need to specify queueName separately

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
            value: "my_module.handler"
        resources:
          limits:
            cpu: 1000m
            memory: 1Gi
          requests:
            cpu: 100m
            memory: 256Mi
```

Install:

```bash
helm install my-actor ./testing/e2e/charts/asya-test-actor -f my-values.yaml
```

## Configuration

### Core Parameters

| Parameter | Description | Required | Default |
|-----------|-------------|----------|---------|
| `name` | Actor name (used as queue name) | Yes | `my-actor` |
| `namespace` | Kubernetes namespace | Yes | `my-namespace` |
| `transport` | Transport name (configured in operator) | Yes | `rabbitmq` |

### Queue Name Resolution

Actor names are resolved to actual queue names based on the transport type (see `router.go:354-369`):

**RabbitMQ:**
- Actor name is used directly as the queue name
- Example: `echo-actor` → RabbitMQ queue `echo-actor`
- No transformation applied

**SQS:**
- Actor name is appended to the SQS base URL
- Format: `{SQSBaseURL}/{actorName}`
- Example: `my-actor` with base URL `https://sqs.us-east-1.amazonaws.com/123456789012` → `https://sqs.us-east-1.amazonaws.com/123456789012/my-actor`
- If SQS base URL is empty, falls back to using actor name directly

**Default:**
- Unknown transport types use the actor name directly
- No transformation applied

**Important:** This resolution is stateless and happens at the sidecar routing layer. The same actor name in envelope routes is consistently resolved to the same queue across all actors in the system.

### Scaling Configuration (KEDA)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `scaling.enabled` | Enable KEDA autoscaling | `true` |
| `scaling.minReplicas` | Minimum replicas (0 = scale to zero) | `0` |
| `scaling.maxReplicas` | Maximum replicas | `10` |
| `scaling.pollingInterval` | Polling interval (seconds) | `10` |
| `scaling.cooldownPeriod` | Cooldown period (seconds) | `60` |
| `scaling.queueLength` | Messages per replica | `5` |

### Advanced Scaling Modifiers (KEDA)

For more sophisticated scaling logic, you can use KEDA's advanced scaling modifiers:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `scaling.advanced.formula` | Custom scaling formula (e.g., `"ceil(queueLength / 10)"`) | `""` |
| `scaling.advanced.target` | Target value for the metric | `""` |
| `scaling.advanced.activationTarget` | Threshold to scale from 0 to 1 replica | `""` |
| `scaling.advanced.metricType` | Metric type: `AverageValue`, `Value`, or `Utilization` | `""` |
| `scaling.advanced.restoreToOriginalReplicaCount` | Restore replicas when deleted | `false` |

**Scaling Formulas:**

Formulas allow custom calculations for desired replica count. Available variables depend on the scaler:
- For RabbitMQ/SQS: `queueLength` (number of messages in queue)

**Examples:**
- `"ceil(queueLength / 10)"` - One replica per 10 messages, rounded up
- `"queueLength * 0.5"` - Scale proportionally with half the queue length
- `"min(ceil(queueLength / 5), 20)"` - Cap at 20 replicas regardless of queue depth

**Metric Types:**
- `AverageValue`: Scale based on average metric value per pod (default)
- `Value`: Scale based on absolute metric value
- `Utilization`: Scale based on resource utilization percentage

**Activation Target:**

The activation threshold determines when to scale from 0 to 1 replica. For example:
- `activationTarget: "10"` means scale to 1 replica when queue > 10 messages
- Without this, any message in the queue will trigger scaling from 0 to 1

### Workload Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `workload.kind` | Workload kind (`Deployment` or `StatefulSet`) | `Deployment` |
| `workload.replicas` | Number of replicas (ignored if scaling enabled) | `1` |
| `workload.pythonExecutable` | Python executable path for runtime | `python3` |
| `workload.template.spec.containers` | Container definitions | See examples |

**IMPORTANT:**
- Do NOT set `command` on your runtime container - the operator automatically injects it
- Do NOT try to configure the sidecar - the operator handles it automatically

#### Python Runtime Configuration

The operator injects `command: ["python3", "/opt/asya/asya_runtime.py"]` into all runtime containers. Your container must meet these requirements:

1. **Python availability**: `python3` must be in PATH (or override via `workload.pythonExecutable`)
2. **Handler importability**: Your function must be importable via `ASYA_HANDLER`

**Custom Python executable:**
```yaml
workload:
  pythonExecutable: "/opt/conda/bin/python"  # Or "python3.11"
```

**Handler import resolution:**
```yaml
# Standalone script at /app/script.py with function 'process'
env:
  - name: PYTHONPATH
    value: "/app"
  - name: ASYA_HANDLER
    value: "script.process"

# Package at /app/my_pkg/handler.py with function 'predict'
env:
  - name: PYTHONPATH
    value: "/app"
  - name: ASYA_HANDLER
    value: "my_pkg.handler.predict"
```

#### Workload Kinds

The Asya🎭 operator supports two Kubernetes workload kinds for AsyncActor resources. Choose the kind based on your actor's characteristics:

**Note:** Only workload kinds with KEDA scaling support (Deployment and StatefulSet) are supported. Pod workload kind is NOT supported because it lacks the `/scale` subresource required for KEDA autoscaling.

##### 1. Deployment (Default)

**Use when:** Your actor is stateless and handles messages independently

**Characteristics:**
- ✅ Stateless message processing
- ✅ Replicas can be created/destroyed freely
- ✅ Best for scale-to-zero with KEDA
- ✅ Rolling updates supported
- ❌ No persistent storage per pod
- ❌ No stable network identity

**Example use cases:**
- Image processing actors
- Text analysis/NLP actors
- API integration actors
- Data transformation actors

**Configuration:**
```yaml
workload:
  kind: Deployment  # or omit (Deployment is default)
  template:
    spec:
      containers:
      - name: asya-runtime
        image: python:3.13-slim
        env:
          - name: ASYA_HANDLER
            value: "handlers.process"
```

##### 2. StatefulSet

**Use when:** Your actor needs persistent storage or stable network identity

**Characteristics:**
- ✅ Stable, unique network identity (pod-0, pod-1, etc.)
- ✅ Persistent volume claims per pod
- ✅ Ordered deployment and scaling
- ✅ Sticky pod identity on rescheduling
- ⚠️ Slower scaling (sequential)
- ⚠️ Requires storage provisioner

**Example use cases:**
- Actors maintaining local state/cache
- Actors with large model files (persistent volume)
- Actors requiring consistent identity
- Database-backed actors with local cache

**Configuration:**
```yaml
workload:
  kind: StatefulSet
  template:
    spec:
      containers:
      - name: asya-runtime
        image: my-registry.io/stateful-actor:v1
        env:
          - name: ASYA_HANDLER
            value: "handlers.stateful_process"
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

#### Choosing the Right Workload Type

| Requirement | Recommended Type |
|------------|------------------|
| Stateless, continuous message processing | **Deployment** |
| Scale-to-zero capability needed | **Deployment** |
| Fast horizontal scaling required | **Deployment** |
| Batch processing | **Deployment** |
| Need persistent storage per replica | **StatefulSet** |
| Need stable network identity | **StatefulSet** |
| Large models loaded from persistent volume | **StatefulSet** |

#### Default Behavior

If `workload.kind` is not specified, the operator defaults to **Deployment**, which is suitable for 95% of use cases.

## Examples

### Example 1: Simple Python Actor

```yaml
name: echo-actor
namespace: asya
# Actor name automatically used as queue name

# Transport reference (configured at operator installation)
transport: rabbitmq

workload:
  template:
    spec:
      containers:
      - name: asya-runtime
        image: python:3.13-slim
        env:
          - name: ASYA_HANDLER
            value: "handlers.echo"
```

### Example 2: Actor with Custom Image and Resources

```yaml
name: nlp-actor
namespace: asya
# Actor name automatically used as queue name

transport: rabbitmq

scaling:
  enabled: true
  minReplicas: 1
  maxReplicas: 20
  queueLength: 10

workload:
  template:
    spec:
      containers:
      - name: asya-runtime
        image: my-registry.io/nlp-model:v1.0
        env:
          - name: ASYA_HANDLER
            value: "nlp_handlers.process"
          - name: MODEL_PATH
            value: "/models/bert"
        resources:
          limits:
            cpu: 4000m
            memory: 8Gi
          requests:
            cpu: 2000m
            memory: 4Gi
```

### Example 3: GPU Actor with Scale-to-Zero

```yaml
name: gpu-inference
namespace: asya
# Actor name automatically used as queue name

transport: rabbitmq

scaling:
  enabled: true
  minReplicas: 0  # Scale to zero when idle
  maxReplicas: 5
  queueLength: 1  # One message per GPU

workload:
  template:
    spec:
      containers:
      - name: asya-runtime
        image: nvidia/cuda:12.0-runtime-ubuntu22.04
        env:
          - name: ASYA_HANDLER
            value: "gpu_handlers.inference"
        resources:
          limits:
            nvidia.com/gpu: 1
            memory: 16Gi
            cpu: 4000m
          requests:
            nvidia.com/gpu: 1
            memory: 8Gi
            cpu: 2000m
```

### Example 4: Advanced Scaling with Custom Formula

```yaml
name: batch-processor
namespace: asya
# Actor name automatically used as queue name

transport: rabbitmq

scaling:
  enabled: true
  minReplicas: 0
  maxReplicas: 50
  pollingInterval: 10
  cooldownPeriod: 60
  queueLength: 10  # Base threshold (used if no formula)

  advanced:
    formula: "ceil(queueLength / 10)"
    target: "10"
    activationTarget: "5"
    metricType: "AverageValue"

workload:
  template:
    spec:
      containers:
      - name: asya-runtime
        image: python:3.13-slim
        env:
          - name: ASYA_HANDLER
            value: "handlers.batch_process"
        resources:
          limits:
            cpu: 2000m
            memory: 2Gi
```

### Example 5: StatefulSet with Persistent Storage

```yaml
name: model-cache-actor
namespace: asya
# Actor name automatically used as queue name

transport: rabbitmq

scaling:
  enabled: true
  minReplicas: 1  # Keep at least 1 replica for model caching
  maxReplicas: 3
  queueLength: 10

workload:
  kind: StatefulSet
  template:
    spec:
      containers:
      - name: asya-runtime
        image: my-registry.io/llm-inference:v2
        env:
          - name: ASYA_HANDLER
            value: "handlers.inference"
          - name: MODEL_CACHE_DIR
            value: "/models"
        volumeMounts:
        - name: model-cache
          mountPath: /models
        resources:
          limits:
            cpu: 8000m
            memory: 32Gi
            nvidia.com/gpu: 1
  volumeClaimTemplates:
  - metadata:
      name: model-cache
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: fast-ssd
      resources:
        requests:
          storage: 100Gi
```

### Example 6: SQS Transport

```yaml
name: sqs-actor
namespace: asya
# Actor name automatically used as queue name

# Reference to SQS transport configured at operator installation
transport: sqs

workload:
  template:
    spec:
      containers:
      - name: asya-runtime
        image: python:3.13-slim
        env:
          - name: ASYA_HANDLER
            value: "handlers.process"
          - name: AWS_REGION
            value: "us-east-1"
```

## Using in Helmfile

You can deploy multiple actors using Helmfile:

```yaml
releases:
  - name: actor-echo
    chart: ./testing/e2e/charts/asya-test-actor
    namespace: asya
    values:
      - name: echo-actor
        # Actor name automatically used as queue name
        transport: rabbitmq
        workload:
          template:
            spec:
              containers:
              - name: asya-runtime
                image: python:3.13-slim
                env:
                  - name: ASYA_HANDLER
                    value: "handlers.echo"

  - name: actor-nlp
    chart: ./testing/e2e/charts/asya-test-actor
    namespace: asya
    values:
      - name: nlp-actor
        # Actor name automatically used as queue name
        transport: rabbitmq
        workload:
          template:
            spec:
              containers:
              - name: asya-runtime
                image: my-registry.io/nlp-model:v1.0
                env:
                  - name: ASYA_HANDLER
                    value: "handlers.nlp"
```

## What the Operator Automatically Injects

When you create an AsyncActor resource using this chart, the operator will:

1. **Inject sidecar container** with:
   - Image: `asya-sidecar:latest` (configurable via CRD if needed)
   - Environment variables for queue transport
   - Volume mounts for Unix socket communication

2. **Inject runtime command** on your container:
   - Sets `command: ["python", "/opt/asya/asya_runtime.py"]` if not specified
   - Adds `ASYA_SOCKET_PATH` environment variable
   - Mounts asya_runtime.py from ConfigMap

3. **Create supporting resources**:
   - Deployment or StatefulSet based on `workload.kind`
   - KEDA ScaledObject (if scaling enabled)
   - Required volumes and volume mounts

## Troubleshooting

### Actor pods not starting

Check if the operator is running:
```bash
kubectl get pods -n asya-system
kubectl logs -n asya-system -l app=asya-operator
```

### KEDA not scaling

Ensure KEDA is installed:
```bash
kubectl get pods -n keda
```

Check KEDA ScaledObject:
```bash
kubectl get scaledobject -n <namespace>
kubectl describe scaledobject <actor-name>-scaled-object
```

### Messages not being consumed

Check RabbitMQ connectivity:
```bash
kubectl exec -it <actor-pod> -c sidecar -- env | grep RABBITMQ
```

Check sidecar logs:
```bash
kubectl logs <actor-pod> -c sidecar
```

## Uninstallation

```bash
helm uninstall my-actor
```

## Development

### Testing Locally

```bash
# Validate the chart
helm lint ./testing/e2e/charts/asya-test-actor

# Dry run
helm install my-actor ./testing/e2e/charts/asya-test-actor \
  --dry-run --debug \
  -f my-values.yaml

# Template output
helm template my-actor ./testing/e2e/charts/asya-test-actor \
  -f my-values.yaml
```

### Running Helm Tests

After installing the chart, you can run the Helm tests to validate the deployment:

```bash
# Install the chart
helm install my-actor ./testing/e2e/charts/asya-test-actor -f my-values.yaml

# Run tests
helm test my-actor -n <namespace>
```

The test suite includes:
1. **test-dependencies**: Validates CRDs, operator, and KEDA are installed
2. **test-queue-exists**: Validates the actor's queue exists in the transport (RabbitMQ/SQS)
3. **test-asyncactor-created**: Validates AsyncActor resource exists with correct queue and transport
4. **test-asyncactor-spec**: Validates scaling configuration and workload kind
5. **test-labels-annotations**: Validates standard and custom labels/annotations
6. **test-advanced-scaling**: Validates advanced KEDA scaling modifiers (formula, target, etc.)

Test pods are automatically deleted after successful completion (`hook-delete-policy: before-hook-creation,hook-succeeded`).

#### Queue Validation Test

The `test-queue-exists` test validates that the operator has successfully created the queue in the configured transport. This test:

- Waits up to 30 seconds for the queue to be created
- For RabbitMQ: Uses the management API to check queue existence and display queue stats
- For SQS: Uses AWS CLI to verify queue exists and display queue attributes

**RabbitMQ Configuration:**

The test uses default RabbitMQ connection settings. Override via environment variables if needed:

```yaml
# In your values.yaml - these are defaults and typically don't need to be changed
transport: rabbitmq
# Default RabbitMQ settings (used by test):
# RABBITMQ_HOST: rabbitmq.default.svc.cluster.local
# RABBITMQ_PORT: 15672 (management API)
# RABBITMQ_USER: guest
# RABBITMQ_PASS: guest
```

**SQS Configuration:**

For SQS, provide AWS credentials (prefer IRSA in production):

```yaml
transport: sqs
# For testing only - use IRSA in production
awsAccessKeyId: "YOUR_ACCESS_KEY"
awsSecretAccessKey: "YOUR_SECRET_KEY"
```

The test validates the queue exists and displays:
- RabbitMQ: message count, consumer count, durability
- SQS: approximate message counts, visibility timeout

## License

See main project license.
