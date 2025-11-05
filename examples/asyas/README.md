# Actor Examples

This directory contains example Actor manifests demonstrating various configurations.

## Quick Start

```bash
# Create RabbitMQ secret first
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

**Minimal configuration** for getting started quickly.

- RabbitMQ transport
- Default sidecar settings
- Basic Deployment
- Default KEDA autoscaling (0-50 replicas)

**Use case:** Learning, testing, simple message processing

```bash
kubectl apply -f simple-actor.yaml
```

---

### 2. [sqs-actor.yaml](./sqs-actor.yaml)

**Production ML inference** with AWS SQS.

- AWS SQS transport (requires IAM role)
- Custom sidecar version
- GPU resources
- Aggressive scaling (1-100 replicas)
- Model cache volume
- Short queue length for slow processing

**Use case:** ML inference, GPU workloads, AWS environments

**Prerequisites:**
```bash
# Attach IAM role to service account
kubectl annotate serviceaccount default \
  eks.amazonaws.com/role-arn=arn:aws:iam::ACCOUNT:role/sqs-role
```

```bash
kubectl apply -f sqs-actor.yaml
```

---

### 3. [statefulset-actor.yaml](./statefulset-actor.yaml)

**Stateful processing** with stable identity and persistent storage.

- StatefulSet workload
- Document processing use case
- Persistent volume for caching

**Use case:** Stateful workloads, caching, stable network identity

**Note:** Full StatefulSet support (including volumeClaimTemplates) is coming soon. Currently you need to manually add volumeClaimTemplates to the created StatefulSet.

```bash
kubectl apply -f statefulset-actor.yaml

# Manually add volumeClaimTemplates
kubectl edit statefulset stateful-processor
```

---

### 4. [multi-container-actor.yaml](./multi-container-actor.yaml)

**Multiple containers** in the runtime pod.

- Video processing + S3 uploader
- Shared volume between containers
- Sidecar is automatically injected as first container
- Long processing timeout (10 minutes)

**Use case:** Multi-stage processing, sidecar patterns, video/media processing

```bash
kubectl apply -f multi-container-actor.yaml
```

---

### 5. [custom-sidecar-actor.yaml](./custom-sidecar-actor.yaml)

**Custom sidecar configuration** showing all customization options.

- Specific sidecar version
- Custom resource limits
- Additional environment variables
- Custom socket path and size
- Tracing configuration

**Use case:** Advanced configurations, debugging, performance tuning

```bash
kubectl apply -f custom-sidecar-actor.yaml
```

---

### 6. [no-scaling-actor.yaml](./no-scaling-actor.yaml)

**Fixed replicas** without KEDA autoscaling.

- Scaling disabled
- Fixed 3 replicas
- Steady workload

**Use case:** Predictable load, no autoscaling needed, development

```bash
kubectl apply -f no-scaling-actor.yaml
```

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

### Check Created Resources

```bash
# Check Deployment
kubectl get deployment <actor-name>

# Check ScaledObject
kubectl get scaledobject <actor-name>

# Check HPA
kubectl get hpa
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
kubectl logs <pod-name> -c sidecar

# Check runtime logs
kubectl logs <pod-name> -c runtime

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

## Testing Scenarios

### Test Scale to Zero

```bash
# Apply actor
kubectl apply -f simple-actor.yaml

# Ensure queue is empty
# Wait for cooldownPeriod (default 60s)

# Check replicas
kubectl get deployment hello-actor -o jsonpath='{.spec.replicas}'
# Should be 0
```

### Test Scale Up

```bash
# Send messages to queue
# For RabbitMQ:
kubectl exec -n rabbitmq rabbitmq-0 -- \
  rabbitmqadmin publish exchange=amq.default \
  routing_key=hello-queue payload="test message"

# Watch pods scale up
kubectl get pods -w
```

### Test Multiple Actors

```bash
# Create multiple actors on different queues
kubectl apply -f simple-actor.yaml
kubectl apply -f custom-sidecar-actor.yaml

# Each gets its own Deployment and ScaledObject
kubectl get actors
kubectl get deployments
```

## Prerequisites

### Required

- Kubernetes 1.23+
- KEDA 2.0+ installed
- Asya Operator installed

### Optional (depending on example)

- RabbitMQ for RabbitMQ examples
- AWS IAM role for SQS examples
- GPU node pool for ML examples
- Persistent volumes for StatefulSet examples

## Next Steps

After trying these examples:

1. **Customize** for your use case
2. **Add monitoring** with Prometheus/Grafana
3. **Configure alerts** for scaling events
4. **Set up CI/CD** for automated deployments
5. **Review** [operator README](../README.md) for advanced topics
