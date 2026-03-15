# asya-actor Helm Chart

Generic Helm chart for deploying AsyncActor resources with comprehensive health validation.

## Features

- Flexible AsyncActor CRD deployment
- Pre-install validation (CRD, KEDA, operator readiness)
- Crew actors health checks (x-sink, x-sump)
- Queue health validation (RabbitMQ/SQS)
- Deployment readiness checks
- AsyncActor status validation
- KEDA autoscaling integration

## Prerequisites

- Kubernetes cluster (1.24+)
- Crossplane installed:
  ```bash
  helm repo add crossplane-stable https://charts.crossplane.io/stable
  helm install crossplane crossplane-stable/crossplane \
    --namespace crossplane-system --create-namespace
  ```
- Asya compositions installed:
  ```bash
  kubectl apply -f https://github.com/deliveryhero/asya/releases/latest/download/asya-crossplane.yaml
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
  --set default.image=my-image:latest \
  --set default.handler=my_module.handler
```

### Using values file

```bash
# Create custom-values.yaml
cat > custom-values.yaml <<EOF
name: text-processor
namespace: production
transport: rabbitmq

default:
  scaling:
    enabled: true
    minReplicaCount: 2
    maxReplicaCount: 20
    queueLength: 10
  image: my-text-processor:v1.0
  imagePullPolicy: IfNotPresent
  handler: processors.text_handler
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
| `transport` | Transport name (rabbitmq or sqs) | `rabbitmq` |

### Scaling Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `scaling.enabled` | Enable KEDA autoscaling | `true` |
| `scaling.minReplicaCount` | Minimum replicas | `1` |
| `scaling.maxReplicaCount` | Maximum replicas | `10` |
| `scaling.pollingInterval` | KEDA polling interval (seconds) | `10` |
| `scaling.cooldownPeriod` | KEDA cooldown period (seconds) | `60` |
| `scaling.queueLength` | Target queue length per replica | `5` |

### Actor Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `default.image` | Runtime container image | `my-actor:latest` |
| `default.imagePullPolicy` | Image pull policy | `IfNotPresent` |
| `default.handler` | Python handler dotted path (e.g. `module.func`) | `my_module.my_handler` |
| `default.env` | Runtime container environment variables | `[]` |
| `default.resources` | Runtime container resource requests/limits | See values.yaml |

### Health Check Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `healthChecks.preInstall.enabled` | Enable pre-install validation | `true` |
| `healthChecks.crew.enabled` | Enable crew actors check | `true` |
| `healthChecks.crew.requiredActors` | List of required crew actors | `[x-sink, x-sump]` |
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

### Simple Handler

```yaml
name: simple-processor
transport: rabbitmq
default:
  image: my-processor:latest
  handler: handlers.process_payload
```

### Custom Crew Actors

```yaml
name: my-actor
transport: rabbitmq

healthChecks:
  crew:
    enabled: true
    requiredActors:
    - x-sink
    - x-sump
    - custom-logger
    - custom-metrics
```

## Troubleshooting

### Pre-install validation fails

Check dependencies:
```bash
kubectl get xrd asyncactors.asya.sh
kubectl get deployment crossplane -n crossplane-system
kubectl get crd scaledobjects.keda.sh
```

### Queue health check fails

Check Crossplane logs and queue status:
```bash
kubectl logs -n crossplane-system deployment/crossplane

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

Note: This removes the AsyncActor resource. Crossplane will clean up associated workloads and queues.
