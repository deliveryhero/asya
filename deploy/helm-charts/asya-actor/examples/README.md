# asya-actor Chart Examples

This directory contains example configurations for deploying AsyncActors using the generic asya-actor Helm chart.

## Examples Overview

### echo-actor.yaml
Basic echo actor deployment with RabbitMQ transport.

**Features:**
- Payload mode handler
- RabbitMQ transport
- KEDA autoscaling (1-10 replicas)
- All health checks enabled

**Deploy:**
```bash
helm install echo-actor deploy/helm-charts/asya-actor \
  -f deploy/helm-charts/asya-actor/examples/echo-actor.yaml
```

**Test:**
```bash
helm test echo-actor
```

### sqs-actor.yaml
Production SQS processor with advanced scaling.

**Features:**
- SQS transport with advanced KEDA scaling
- Higher replica limits (2-50)
- AWS credentials from secrets
- Custom polling and cooldown settings

**Deploy:**
```bash
# Create AWS credentials secret first
kubectl create secret generic aws-credentials \
  --from-literal=access-key-id=YOUR_ACCESS_KEY \
  --from-literal=secret-access-key=YOUR_SECRET_KEY

helm install sqs-processor deploy/helm-charts/asya-actor \
  -f deploy/helm-charts/asya-actor/examples/sqs-actor.yaml \
  -n production --create-namespace
```

**Test:**
```bash
helm test sqs-processor -n production
```

## Quick Start

### 1. Install Prerequisites

```bash
# Install AsyncActor CRD
kubectl apply -f src/asya-operator/config/crd/

# Install Asya🎭 operator
helm install asya-operator deploy/helm-charts/asya-operator \
  -n asya-system --create-namespace

# Install KEDA (for autoscaling)
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda \
  -n keda-system --create-namespace

# Install crew actors
helm install asya-crew deploy/helm-charts/asya-crew \
  -n default
```

### 2. Deploy an Actor

```bash
# Using echo-actor example
helm install my-echo deploy/helm-charts/asya-actor \
  -f deploy/helm-charts/asya-actor/examples/echo-actor.yaml
```

### 3. Verify Health

```bash
# Run Helm tests
helm test my-echo

# Check AsyncActor status
kubectl get asyncactor echo-actor

# Check workload
kubectl get deployment echo-actor
kubectl get pods -l app.kubernetes.io/name=echo-actor
```

## Creating Custom Values

Copy an example and modify:

```bash
cp deploy/helm-charts/asya-actor/examples/echo-actor.yaml my-actor.yaml

# Edit my-actor.yaml
# Change: name, image, handler, resources, etc.

helm install my-actor deploy/helm-charts/asya-actor -f my-actor.yaml
```

## Health Check Configuration

### Disable All Health Checks (for quick testing)

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

### Selective Health Checks

```yaml
healthChecks:
  # Keep pre-install validation
  preInstall:
    enabled: true
  # Skip crew check if crew not installed yet
  crew:
    enabled: false
  # Keep queue and deployment checks
  queue:
    enabled: true
    timeoutSeconds: 300
  deployment:
    enabled: true
    timeoutSeconds: 600
  status:
    enabled: true
```

### Custom Crew Actors

```yaml
healthChecks:
  crew:
    enabled: true
    requiredActors:
    - happy-end
    - error-end
    - custom-logger      # Your custom crew actor
    - custom-metrics     # Another custom crew actor
```

## Common Patterns

### StatefulSet Workload

```yaml
workload:
  kind: StatefulSet
  template:
    spec:
      containers:
      - name: asya-runtime
        image: my-stateful-processor:latest
        env:
        - name: ASYA_HANDLER
          value: processors.stateful_handler
        volumeMounts:
        - name: data
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      resources:
        requests:
          storage: 10Gi
```

### Envelope Mode Handler

```yaml
workload:
  template:
    spec:
      containers:
      - name: asya-runtime
        image: my-envelope-processor:latest
        env:
        - name: ASYA_HANDLER
          value: processors.envelope_handler
        - name: ASYA_HANDLER_MODE
          value: envelope  # Process full envelope, not just payload
```

### Minimal Scaling (Development)

```yaml
scaling:
  enabled: true
  minReplicas: 0  # Scale to zero when idle
  maxReplicas: 1
  queueLength: 1
```

### Aggressive Scaling (Production)

```yaml
scaling:
  enabled: true
  minReplicas: 5
  maxReplicas: 100
  pollingInterval: 5     # Check every 5s
  cooldownPeriod: 30     # Scale down after 30s
  queueLength: 2         # Scale up at 2 messages per replica
```

## Troubleshooting

### Pre-install validation fails

```bash
# Check CRD
kubectl get crd asyncactors.asya.sh

# Check operator
kubectl get deployment asya-operator -n asya-system
kubectl logs -n asya-system deployment/asya-operator

# Check KEDA
kubectl get crd scaledobjects.keda.sh
```

### Queue health check fails

```bash
# For RabbitMQ
kubectl exec asya-rabbitmq-0 -- rabbitmqctl list_queues

# For SQS
aws sqs list-queues --region us-east-1

# Check operator logs
kubectl logs -n asya-system deployment/asya-operator
```

### Deployment readiness fails

```bash
# Check pods
kubectl get pods -l app.kubernetes.io/name=<actor-name>
kubectl describe pod <pod-name>
kubectl logs <pod-name> asya-sidecar
kubectl logs <pod-name> asya-runtime

# Check AsyncActor status
kubectl describe asyncactor <actor-name>
```

## Cleanup

```bash
# Uninstall actor (removes AsyncActor, workload, and queue)
helm uninstall my-echo

# Uninstall crew
helm uninstall asya-crew

# Uninstall operator
helm uninstall asya-operator -n asya-system

# Uninstall KEDA
helm uninstall keda -n keda-system
```
