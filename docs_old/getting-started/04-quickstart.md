# Quick Start

Get Asya🎭 up and running in minutes.

## Prerequisites

- Kubernetes cluster (Minikube, kind, or cloud provider)
- kubectl configured
- Helm 3.0+
- Docker (for building images)

## Option 1: Full OSS Stack (Recommended)

Deploy the complete stack with infrastructure and monitoring on Minikube:

```bash
# Navigate to deployment directory
cd examples/deployment-minikube

# Deploy everything (RabbitMQ, PostgreSQL, MinIO, Prometheus, Grafana, KEDA, Asya🎭)
./deploy.sh

# Wait for deployment to complete (~5-10 minutes)
# The script will show progress

# Verify the deployment
./test-e2e.sh
```

This gives you:
- ✅ RabbitMQ message queue
- ✅ PostgreSQL database
- ✅ MinIO object storage
- ✅ Prometheus + Grafana monitoring
- ✅ KEDA autoscaling
- ✅ Asya🎭 operator and gateway
- ✅ Example actors

### Access Services

```bash
# Grafana (metrics and dashboards)
../scripts/port-forward-grafana.sh
# Open http://localhost:3000

# RabbitMQ Management UI
kubectl port-forward -n asya svc/rabbitmq 15672:15672
# Open http://localhost:15672

# Asya🎭 Gateway (MCP API)
kubectl port-forward -n asya svc/asya-gateway 8080:8080
```

See [examples/deployment-minikube/README.md](../../examples/deployment-minikube/README.md) for more details.

## Option 2: Minimal Framework

Install just the Asya🎭 operator without infrastructure (bring your own queue/storage):

```bash
# Install CRDs
kubectl apply -f src/asya-operator/config/crd/

# Install operator via Helm
helm install asya-operator deploy/helm-charts/asya-operator \
  --namespace asya-system \
  --create-namespace

# Verify installation
kubectl get pods -n asya-system
```

See [examples/deployment-minimal/README.md](../../examples/deployment-minimal/README.md) for more details.

## Deploy Your First Actor

Create a simple actor:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello-actor
  namespace: default
spec:
  # Actor name is automatically used as the queue name
  # Transport references operator-configured transport
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
          env:
          - name: ASYA_HANDLER
            value: "hello.process"
```

Apply it:

```bash
kubectl apply -f hello-actor.yaml
```

Check status:

```bash
# List actors
kubectl get asyas

# Get details
kubectl describe asya hello-actor

# Check created resources
kubectl get deployment hello-actor
kubectl get scaledobject hello-actor
```

## Next Steps

- [Installation Guide](03-installation.md) - Detailed installation instructions
- [Core Concepts](02-concepts.md) - Understanding Asya🎭 concepts
- [Component Documentation](../architecture/asya-gateway.md) - Deep dive into components
- [Example Actors](../guides/examples-actors.md) - More actor examples
