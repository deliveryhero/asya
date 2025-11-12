# asya-actor Helm Chart

Generic Helm chart for deploying AsyncActor resources with comprehensive health validation.

## Features

- Flexible AsyncActor CRD deployment
- Pre-install validation (CRD, KEDA, operator readiness)
- Crew actors health checks (happy-end, error-end)
- Queue health validation (RabbitMQ/SQS)
- Deployment readiness checks
- AsyncActor status validation
- Support for both Deployment and StatefulSet workloads
- KEDA autoscaling integration

## Prerequisites

- Kubernetes cluster (1.24+)
- AsyncActor CRD installed:
  ```bash
  kubectl apply -f src/asya-operator/config/crd/
  ```
- Asya🎭 operator running:
  ```bash
  helm install asya-operator deploy/helm-charts/asya-operator \
    -n asya-system --create-namespace
  ```
- KEDA installed (if scaling is enabled):
  ```bash
  helm repo add kedacore https://kedacore.github.io/charts
  helm install keda kedacore/keda -n keda-system --create-namespace
  ```
- Transport configured (RabbitMQ or SQS)

## Installation

### Basic Installation

```bash
helm install my-actor deploy/helm-charts/asya-actor \
  --set name=my-actor \
  --set transport=rabbitmq \
  --set workload.template.spec.containers[0].image=my-image:latest \
  --set workload.template.spec.containers[0].env[0].name=ASYA_HANDLER \
  --set workload.template.spec.containers[0].env[0].value=my_module.handler
```

### Using values file

```bash
# Create custom-values.yaml
cat > custom-values.yaml <<EOF
name: text-processor
namespace: production
transport: rabbitmq

scaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 20
  queueLength: 10

workload:
  kind: Deployment
  template:
    spec:
      containers:
      - name: asya-runtime
        image: my-text-processor:v1.0
        imagePullPolicy: IfNotPresent
        env:
        - name: ASYA_HANDLER
          value: processors.text_handler
        resources:
          requests:
            cpu: 200m
            memory: 256Mi
          limits:
            cpu: 1000m
            memory: 1Gi
EOF

helm install text-processor deploy/helm-charts/asya-actor \
  -f custom-values.yaml
```

## Configuration

### Core Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `name` | Actor name (must be unique) | `my-actor` |
| `namespace` | Deployment namespace | `default` |
| `transport` | Transport name (must exist in operator config) | `rabbitmq` |

### Scaling Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `scaling.enabled` | Enable KEDA autoscaling | `true` |
| `scaling.minReplicas` | Minimum replicas | `1` |
| `scaling.maxReplicas` | Maximum replicas | `10` |
| `scaling.pollingInterval` | KEDA polling interval (seconds) | `10` |
| `scaling.cooldownPeriod` | KEDA cooldown period (seconds) | `60` |
| `scaling.queueLength` | Target queue length per replica | `5` |

### Workload Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `workload.kind` | Workload type (Deployment or StatefulSet) | `Deployment` |
| `workload.template` | Pod template spec | See values.yaml |

### Health Check Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `healthChecks.preInstall.enabled` | Enable pre-install validation | `true` |
| `healthChecks.crew.enabled` | Enable crew actors check | `true` |
| `healthChecks.crew.requiredActors` | List of required crew actors | `[happy-end, error-end]` |
| `healthChecks.queue.enabled` | Enable queue health check | `true` |
| `healthChecks.queue.timeoutSeconds` | Queue creation timeout | `300` |
| `healthChecks.deployment.enabled` | Enable deployment readiness check | `true` |
| `healthChecks.deployment.timeoutSeconds` | Deployment ready timeout | `600` |
| `healthChecks.status.enabled` | Enable status validation | `true` |

## Running Health Checks

After installation, run health checks:

```bash
helm test my-actor
```

This executes all enabled health check tests:

1. **Crew health check** - Validates required crew actors exist and are ready
2. **Queue health check** - Validates actor queue is created and accessible
3. **Deployment readiness** - Validates workload is ready and pods are running
4. **AsyncActor status** - Validates AsyncActor resource has correct spec and status

## Examples

### Payload Mode Handler

```yaml
name: simple-processor
transport: rabbitmq
workload:
  template:
    spec:
      containers:
      - name: asya-runtime
        image: my-processor:latest
        env:
        - name: ASYA_HANDLER
          value: handlers.process_payload
        - name: ASYA_HANDLER_MODE
          value: payload
```

### Envelope Mode Handler

```yaml
name: route-modifier
transport: rabbitmq
workload:
  template:
    spec:
      containers:
      - name: asya-runtime
        image: my-processor:latest
        env:
        - name: ASYA_HANDLER
          value: handlers.modify_route
        - name: ASYA_HANDLER_MODE
          value: envelope
```

### StatefulSet with Advanced Scaling

```yaml
name: stateful-processor
transport: sqs
workload:
  kind: StatefulSet
  template:
    spec:
      containers:
      - name: asya-runtime
        image: my-processor:latest
        env:
        - name: ASYA_HANDLER
          value: handlers.stateful_handler

scaling:
  enabled: true
  minReplicas: 1
  maxReplicas: 50
  advanced:
    triggers:
    - type: aws-sqs-queue
      metadata:
        queueURL: "https://sqs.us-east-1.amazonaws.com/123456789/asya-stateful-processor"
        queueLength: "10"
        awsRegion: "us-east-1"
```

### Custom Crew Actors

```yaml
name: my-actor
transport: rabbitmq

healthChecks:
  crew:
    enabled: true
    requiredActors:
    - happy-end
    - error-end
    - custom-logger
    - custom-metrics
```

## Troubleshooting

### Pre-install validation fails

Check dependencies:
```bash
kubectl get crd asyncactors.asya.sh
kubectl get deployment asya-operator -n asya-system
kubectl get crd scaledobjects.keda.sh
```

### Queue health check fails

Check operator logs and queue status:
```bash
kubectl logs -n asya-system deployment/asya-operator

# For RabbitMQ (adjust pod name if using different RabbitMQ deployment)
kubectl exec -n <namespace> <rabbitmq-pod-name> -- rabbitmqctl list_queues

# For SQS
aws sqs list-queues --region us-east-1
```

### Deployment readiness fails

Check pod status and logs:
```bash
kubectl get pods -n <namespace> -l app.kubernetes.io/name=<actor-name>

# Check sidecar logs
kubectl logs -n <namespace> -l app.kubernetes.io/name=<actor-name> --container asya-sidecar

# Check runtime logs
kubectl logs -n <namespace> -l app.kubernetes.io/name=<actor-name> --container asya-runtime

# Check AsyncActor status
kubectl describe asyncactor <actor-name> -n <namespace>
```

## Disabling Health Checks

For development/testing, disable health checks:

```yaml
healthChecks:
  preInstall:
    enabled: false
  crew:
    enabled: false
  queue:
    enabled: false
  deployment:
    enabled: false
  status:
    enabled: false
```

## Uninstallation

```bash
helm uninstall my-actor
```

Note: This removes the AsyncActor resource. The operator will clean up associated workloads and queues.
