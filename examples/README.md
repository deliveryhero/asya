# Asya Examples

This directory contains examples and reference deployments for the Asya framework.

## Directory Structure

```
examples/
├── asyas/                    # AsyncActor CRD examples
│   ├── simple-actor.yaml
│   ├── sqs-actor.yaml
│   ├── statefulset-actor.yaml
│   ├── multi-container-actor.yaml
│   ├── custom-sidecar-actor.yaml
│   └── no-scaling-actor.yaml
├── deployment-minimal/       # Minimal framework deployment (any K8s)
│   ├── helmfile.yaml
│   └── README.md
├── deployment-minikube/      # Full OSS stack deployment
│   ├── helmfile.yaml
│   ├── example-actor.yaml
│   └── README.md
└── load-test/                # Load testing with simulated AI workloads
    ├── services/             # Mock actor services
    ├── asyas/                # Actor CRDs
    ├── scripts/              # Test scripts
    └── README.md

Note: E2E tests with Kind have moved to ../tests/e2e/
```

## Actor Examples (`asyas/`)

Ready-to-use AsyncActor CRD examples demonstrating different configurations:

- **simple-actor.yaml** - Minimal actor with RabbitMQ
- **sqs-actor.yaml** - Actor using AWS SQS transport
- **statefulset-actor.yaml** - StatefulSet workload type
- **multi-container-actor.yaml** - Multiple runtime containers
- **custom-sidecar-actor.yaml** - Custom sidecar image and configuration
- **no-scaling-actor.yaml** - Disabled autoscaling

Deploy any example:

```bash
kubectl apply -f asyas/simple-actor.yaml
```

## Deployment Examples

> **Note:** For local development and E2E testing with Kind, see [../tests/e2e/](../tests/e2e/)

### Minimal Deployment (`deployment-minimal/`)

Minimal framework deployment for any Kubernetes cluster:

- **KEDA** - Event-driven autoscaling
- **Asya Operator** - CRD controller
- **Asya MCP Gateway** - Optional MCP protocol gateway

Perfect for:
- Getting started with Asya
- Clusters with existing infrastructure (bring your own queue/storage)
- Minimal resource footprint

See [deployment-minimal/README.md](deployment-minimal/README.md) for setup.

### Full OSS Stack (`deployment-minikube/`)

Complete production-ready deployment with open-source infrastructure:

- **RabbitMQ** - Message queue
- **MinIO** - S3-compatible object storage
- **PostgreSQL** - Relational database
- **Prometheus + Grafana** - Metrics and visualization
- **KEDA** - Event-driven autoscaling
- **Asya Framework** - Operator, Gateway, and example actors

Perfect for:
- Production deployments
- Complete self-hosted solution
- Learning the full stack
- Testing with realistic infrastructure

See [deployment-minikube/README.md](deployment-minikube/README.md) for detailed setup.

### Load Test Deployment (`load-test/`)

Simulated AI workload environment for testing autoscaling without GPU requirements:

- **Mock Actors** - Python services with random delays (20-40s, 5-15s, 2-5s)
- **RabbitMQ** - Message queue
- **KEDA** - Event-driven autoscaling (0-30 replicas)
- **Prometheus + Grafana** - Metrics and visualization
- **Load Generator** - Script to send test messages

Perfect for:
- Testing autoscaling behavior on local Minikube
- Demonstrating event-driven scaling without GPU resources
- Load testing and performance tuning
- Understanding Asya's scaling patterns

Key features:
- **Scale from zero**: Actors start at 0 replicas, scale up on demand
- **Fan-out**: Generator produces 3 items per request
- **Realistic delays**: Simulates GPU workloads (image generation: 20-40s, processing: 5-15s, ranking: 2-5s)
- **No GPU needed**: Pure CPU/sleep-based simulation

See [load-test/README.md](load-test/README.md) for detailed setup and demo scenarios.

### Quick Start (Load Test)

```bash
cd load-test
./scripts/deploy.sh              # Deploy infrastructure and actors
./scripts/demo-scenarios.sh      # Run interactive demo scenarios
./scripts/monitor.sh             # Real-time monitoring dashboard
```

Generate custom load:
```bash
# Port-forward RabbitMQ (in separate terminal)
kubectl port-forward -n load-test svc/load-test-rabbitmq 5672:5672

# Send messages
./scripts/generate-load.py 100   # Send 100 messages (300 items due to fan-out)
```

### Quick Start (Full OSS)

**Automated deployment** (recommended):
```bash
cd deployment-minikube
./deploy.sh      # Automated deployment (~5-10 minutes)
./test-e2e.sh        # Verify deployment
```

**Manual deployment**:
```bash
# Install CRDs
kubectl apply -f ../operator/config/crd/

# Deploy full stack
cd deployment-minikube
helmfile sync

# Deploy example actor and secrets
kubectl apply -f secrets.yaml
kubectl apply -f example-actor.yaml
```

**Access services**:
```bash
# Port-forward Grafana (automated script)
../scripts/port-forward-grafana.sh       # Grafana on :3000

# Port-forward other services (use kubectl)
kubectl port-forward -n monitoring svc/prometheus-server 9090:80
kubectl port-forward -n asya svc/asya-gateway 8080:80
kubectl port-forward -n asya svc/rabbitmq 15672:15672
```

## Using These Examples

### As Learning Material

Study the examples to understand:
- How to configure AsyncActor resources
- Different transport types (SQS, RabbitMQ)
- Workload types (Deployment, StatefulSet)
- KEDA autoscaling configuration
- Sidecar injection patterns
- Full stack deployment with monitoring

### As Templates

Copy and modify for your use case:

```bash
# Copy an actor example
cp asyas/simple-actor.yaml my-actor.yaml

# Edit configuration
vim my-actor.yaml

# Deploy
kubectl apply -f my-actor.yaml
```

### For Development and Testing

**Automated test suite**:
```bash
# Run complete test suite (deploy + test + cleanup)
./run-all-tests.sh

# Skip deployment (test existing)
./run-all-tests.sh --skip-deploy

# Skip actor tests (infrastructure only)
./run-all-tests.sh --skip-actors

# Cleanup only
./run-all-tests.sh --cleanup-only
```

**Individual tests**:
- **deployment-minimal**: Quick testing with minimal resources
- **E2E tests**: Full integration testing with monitoring (see `../tests/e2e/`)
- **Actor examples**: Test all example actors (`./test-actors.sh`)

## Choosing the Right Example

| Use Case | Recommendation |
|----------|---------------|
| Learning AsyncActor CRDs | Start with `asyas/simple-actor.yaml` |
| **Local development** | **Use `../tests/e2e/`** (fastest, easiest) |
| Quick local test | Use `deployment-minimal/` |
| Production deployment | Use `deployment-minikube/` as baseline |
| Existing infrastructure | Use `deployment-minimal/` + custom actors |
| Full observability | Use `deployment-minikube/` |
| Load testing / autoscaling demo | Use `load-test/` |
| No GPU, simulate AI workloads | Use `load-test/` |

## Next Steps

1. Review AsyncActor CRD examples in `asyas/`
2. Try `deployment-minimal/` for quick start
3. Deploy `deployment-minikube/` for complete stack
4. See `../deploy/` for production deployment options
5. Read the main README for architecture overview
