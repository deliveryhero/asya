# Development Guide

Local development workflow for Asya🎭 framework.

## Prerequisites

- **Go 1.23+**, **Python 3.13+**, **[uv](https://github.com/astral-sh/uv)** (required for Python)
- **Docker**, **Minikube**, **kubectl**, **Helm 3.0+**, **Make**

### Install Tools

```bash
# macOS
brew install minikube kubectl helm go python@3.13

# uv (Python package manager - required)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Start Minikube
minikube start --cpus=4 --memory=8192
minikube addons enable metrics-server
```

## Quick Workflow

### 1. Deploy Full Stack

```bash
cd tests/gateway-vs-actors/e2e
./scripts/deploy.sh     # Deploy infrastructure + framework
./scripts/test-e2e.sh   # Verify
```

### 2. Develop Component

**Recommended workflow** (same for all components):

```bash
# 1. Make changes
vim src/asya-sidecar/internal/router/router.go

# 2. Run tests
cd src/asya-sidecar && go test ./...

# 3. Build and load
docker build -t asya-sidecar:dev .
minikube image load asya-sidecar:dev

# 4. Restart deployment
kubectl rollout restart deployment my-actor
```

### 3. Test Changes

```bash
# Check logs
kubectl logs -l asya.sh/actor=my-actor -c sidecar -f

# Send test message
kubectl exec -n asya deploy/rabbitmq -- rabbitmqadmin publish \
  exchange=asya routing_key=my-actor \
  payload='{"route":{"actors": ["my-actor"],"current":0},"payload":{"test":true}}'
```

## Component Development

### Operator

**Run locally** (connects to current kubeconfig):
```bash
cd operator
make install           # Install CRD
make run               # Run locally

# In another terminal
kubectl apply -f ../examples/asyas/simple-actor.yaml
```

**Build and deploy**:
```bash
make test
make docker-build IMG=asya-operator:dev
minikube image load asya-operator:dev
kubectl rollout restart deployment -n asya-system asya-operator
```

### Sidecar

**Run locally** with RabbitMQ:
```bash
# Start RabbitMQ
docker run -d --name rabbitmq -p 5672:5672 rabbitmq:3

# Run sidecar
cd src/asya-sidecar
export ASYA_ACTOR_NAME=test-queue
export ASYA_RABBITMQ_URL=amqp://guest:guest@localhost:5672/
go run cmd/sidecar/main.go
```

**Build and deploy**:
```bash
go test ./...
docker build -t asya-sidecar:dev .
minikube image load asya-sidecar:dev
kubectl rollout restart deployment my-actor
```

### Gateway

**Run locally**:
```bash
# Start PostgreSQL
docker run -d --name postgres -p 5432:5432 \
  -e POSTGRES_USER=asya -e POSTGRES_PASSWORD=changeme \
  -e POSTGRES_DB=asya postgres:14

# Run gateway
cd src/asya-gateway
export ASYA_DATABASE_URL=postgresql://asya:changeme@localhost:5432/asya
export ASYA_RABBITMQ_URL=amqp://guest:guest@localhost:5672/
go run cmd/gateway/main.go

# Test
curl http://localhost:8080/health
```

### Runtime

**Run standalone**:
```bash
cd src/asya-runtime

# Create test handler
cat > my_handler.py <<'EOF'
def process(payload):
    return {"result": f"Processed: {payload.get('text', 'no text')}"}
EOF

# Run runtime
export ASYA_HANDLER=my_handler:process
python asya_runtime.py
```

**Test** (requires uv):
```bash
uv run pytest tests/ -v
```

## Testing

```bash
# All tests
make unit-tests           # Unit tests
make integration-tests    # Integration tests

# Individual components
cd operator && make test
cd src/asya-sidecar && go test ./...
cd src/asya-runtime && uv run pytest tests/
```

See [Testing Guide](testing.md) for details.

## Debugging

### Logs

```bash
# Operator
kubectl logs -n asya-system -l app=asya-operator -f

# Gateway
kubectl logs -n asya -l app=asya-gateway -f

# Actor (both containers)
kubectl logs -l asya.sh/actor=my-actor --all-containers -f
```

### Port-Forward

```bash
# Grafana
./scripts/port-forward-grafana.sh

# RabbitMQ Management
kubectl port-forward -n asya svc/rabbitmq 15672:15672
# Open http://localhost:15672 (admin/changeme)

# Gateway
kubectl port-forward -n asya svc/asya-gateway 8080:8080
```

### Interactive

```bash
# Exec into pod
kubectl exec -it <pod-name> -c sidecar -- /bin/sh

# Check socket
ls -la /tmp/sockets/

# RabbitMQ CLI
kubectl exec -n asya deploy/rabbitmq -- rabbitmqctl list_queues
```

## Code Style

```bash
# Format and lint everything (recommended)
make lint

# Auto-fix formatting
make format
```

## Common Tasks

### Add Environment Variable

1. Update config: `internal/config/config.go`
   ```go
   MyVar string `env:"MY_VAR" envDefault:"default"`
   ```

2. Update operator: `internal/controller/asya_controller.go`
   ```go
   Env: []corev1.EnvVar{{Name: "MY_VAR", Value: "value"}}
   ```

3. Update documentation

### Add Metric

1. Define: `internal/metrics/metrics.go`
   ```go
   myMetric = prometheus.NewCounter(...)
   prometheus.MustRegister(myMetric)
   ```

2. Instrument code:
   ```go
   myMetric.Inc()
   ```

3. Update `METRICS.md`

### Modify CRD

1. Edit: `src/asya-operator/config/crd/asya.sh_asyas.yaml`
2. Apply: `kubectl apply -f src/asya-operator/config/crd/`
3. Update examples and documentation

## Next Steps

- [Testing Guide](testing.md) - Test your changes
- [Building Guide](building.md) - Build images
- [Deployment Guide](deploy.md) - Production deployment
