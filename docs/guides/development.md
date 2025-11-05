# Development Guide

Local development workflow for Asya framework.

## Development Environment Setup

### Prerequisites

- **Go 1.23+** - For operator, gateway, sidecar
- **Python 3.13+** - For runtime
- **[uv](https://github.com/astral-sh/uv)** - Python package manager (required for development)
- **Docker** - For building images
- **Minikube** - For local Kubernetes
- **kubectl** - Kubernetes CLI
- **Helm 3.0+** - Package manager
- **Make** - Build automation

### Install Tools

```bash
# Minikube
brew install minikube  # macOS
# or download from https://minikube.sigs.k8s.io/

# kubectl
brew install kubectl

# Helm
brew install helm

# Go (if not installed)
brew install go

# Python (if not installed)
brew install python@3.13

# uv (required for Python development)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Start Minikube

```bash
# Start with enough resources
minikube start --cpus=4 --memory=8192

# Enable addons
minikube addons enable metrics-server

# Verify
kubectl cluster-info
```

## Quick Development Workflow

### 1. Deploy Full Stack

```bash
# Deploy infrastructure + framework
cd examples/deployment-minikube
./deploy.sh

# Verify
./test-e2e.sh
```

### 2. Develop Your Component

**Sidecar:**
```bash
cd src/asya-sidecar

# Make changes
vim internal/router/router.go

# Build
go build -o bin/sidecar ./cmd/sidecar

# Run tests
go test ./...

# Build image
docker build -t asya-sidecar:dev .

# Load into Minikube
minikube image load asya-sidecar:dev

# Update deployment
kubectl set image deployment/my-actor sidecar=asya-sidecar:dev
kubectl rollout restart deployment/my-actor
```

**Operator:**
```bash
cd operator

# Make changes
vim internal/controller/asya_controller.go

# Run tests
make test

# Build and load
make docker-build IMG=asya-operator:dev
minikube image load asya-operator:dev

# Restart operator
kubectl rollout restart deployment -n asya-system asya-operator
```

**Runtime:**
```bash
cd src/asya-runtime

# Make changes
vim asya_runtime.py

# Run tests (requires uv)
uv run pytest tests/

# Build and load
docker build -t asya-runtime:dev .
minikube image load asya-runtime:dev

# Update actor
kubectl set image deployment/my-actor runtime=asya-runtime:dev
kubectl rollout restart deployment/my-actor
```

### 3. Test Changes

```bash
# Check logs
kubectl logs -l app=my-actor -c sidecar -f
kubectl logs -l app=my-actor -c runtime -f

# Send test message
kubectl exec -n asya deploy/rabbitmq -- rabbitmqadmin publish \
  exchange=asya \
  routing_key=my-queue \
  payload='{"route":{"steps":["my-queue"],"current":0},"payload":{"test":true}}'

# Watch processing
kubectl logs -l app=my-actor -f
```

## Component-Specific Development

### Operator Development

**Run locally** (connects to current kubeconfig):
```bash
cd operator

# Install CRD
make install

# Run operator locally
make run

# In another terminal, create test Asya
kubectl apply -f ../examples/asyas/simple-actor.yaml
```

**Debug:**
```bash
# Use delve
dlv debug ./cmd/main.go
```

**Generate code:**
```bash
# After modifying API types
make generate

# Update CRD manifests (manual, no generation)
# Edit config/crd/asya.io_asyas.yaml directly
```

### Sidecar Development

**Run locally** with Docker Compose:
```bash
cd src/asya-sidecar

# Start RabbitMQ
docker-compose up -d rabbitmq

# Run sidecar
export ASYA_QUEUE_NAME=test-queue
export ASYA_RABBITMQ_URL=amqp://guest:guest@localhost:5672/
go run cmd/sidecar/main.go

# In another terminal, start test runtime
cd ../asya-runtime
python asya_runtime.py
```

**Debug:**
```bash
# Use delve
dlv debug ./cmd/sidecar/main.go
```

### Gateway Development

**Run locally:**
```bash
cd src/asya-gateway

# Start PostgreSQL
docker run -d --name postgres -p 5432:5432 \
  -e POSTGRES_USER=asya \
  -e POSTGRES_PASSWORD=changeme \
  -e POSTGRES_DB=asya \
  postgres:14

# Run migrations
export ASYA_DATABASE_URL=postgresql://asya:changeme@localhost:5432/asya
sqitch deploy

# Start gateway
export ASYA_RABBITMQ_URL=amqp://guest:guest@localhost:5672/
go run cmd/gateway/main.go

# Test
curl http://localhost:8080/health
```

**Debug:**
```bash
dlv debug ./cmd/gateway/main.go
```

### Runtime Development

**Run standalone:**
```bash
cd src/asya-runtime

# Create test handler
cat > my_handler.py <<'EOF'
def process(payload):
    print(f"Received: {payload}")
    return {"result": f"Processed: {payload.get('text', 'no text')}"}
EOF

# Run runtime
export ASYA_PROCESS_MODULE=my_handler:process
python asya_runtime.py

# In another terminal, test via socket
python <<'EOF'
import socket, json
s = socket.socket(socket.AF_UNIX)
s.connect("/tmp/sockets/app.sock")
s.sendall(json.dumps({"text": "hello"}).encode())
print(s.recv(1024).decode())
s.close()
EOF
```

## Testing Workflow

### Unit Tests

```bash
# Go components
cd operator && make test
cd src/asya-sidecar && go test ./...
cd src/asya-gateway && go test ./...

# Python components (requires uv)
cd src/asya-runtime && uv run pytest tests/
```

### Integration Tests

```bash
# Docker Compose integration
./scripts/test-integration.sh

# Kubernetes integration
cd examples/deployment-minikube && ./test-e2e.sh
```

### End-to-End Tests

```bash
# Full deployment test
cd examples && ./run-all-tests.sh
```

## Debugging Tips

### View All Logs

```bash
# Operator
kubectl logs -n asya-system -l app=asya-operator -f

# Gateway
kubectl logs -n asya -l app=asya-gateway -f

# Actor (both containers)
kubectl logs -l app=my-actor --all-containers -f
```

### Port-Forward Services

```bash
# Grafana
./scripts/port-forward-grafana.sh

# RabbitMQ Management
kubectl port-forward -n asya svc/rabbitmq 15672:15672

# PostgreSQL
kubectl port-forward -n asya svc/postgresql 5432:5432

# Gateway
kubectl port-forward -n asya svc/asya-gateway 8080:8080
```

### Access RabbitMQ

```bash
# Management UI
kubectl port-forward -n asya svc/rabbitmq 15672:15672
# Open http://localhost:15672 (admin/changeme)

# CLI
kubectl exec -n asya deploy/rabbitmq -- rabbitmqctl list_queues
kubectl exec -n asya deploy/rabbitmq -- rabbitmqadmin list exchanges
kubectl exec -n asya deploy/rabbitmq -- rabbitmqadmin list bindings
```

### Interactive Debugging

```bash
# Exec into pod
kubectl exec -it <pod-name> -c sidecar -- /bin/sh
kubectl exec -it <pod-name> -c runtime -- /bin/bash

# Check socket
ls -la /tmp/sockets/

# Test socket connection
nc -U /tmp/sockets/app.sock
```

## Code Style

### Go

```bash
# Format only go modules
make fmt

# Format and lint (via pre-commit)
make lint
```

### Python

All Python formatting and linting is handled via `uv`:

```bash
# Format and lint (via pre-commit)
make lint

# Or run manually via uv
uv run black .
uv run ruff check .
```

## Hot Reload Workflow

### Air (Go hot reload)

```bash
# Install air
go install github.com/cosmtrek/air@latest

# Run with hot reload
cd src/asya-sidecar
air

# Or use custom config
air -c .air.toml
```

### Watchmedo (Python hot reload)

```bash
# Install watchdog via uv
uv pip install watchdog

# Run with hot reload
uv run watchmedo auto-restart -d . -p '*.py' -- python asya_runtime.py
```

## Common Development Tasks

### Add New Environment Variable

1. **Update config** (`internal/config/config.go`):
   ```go
   MyNewVar string `env:"MY_NEW_VAR" envDefault:"default"`
   ```

2. **Update operator** (`internal/controller/asya_controller.go`):
   ```go
   Env: []corev1.EnvVar{
       {Name: "MY_NEW_VAR", Value: "value"},
   }
   ```

3. **Update documentation**

### Add New Metric

1. **Define metric** (`internal/metrics/metrics.go`):
   ```go
   myMetric = prometheus.NewCounter(...)
   prometheus.MustRegister(myMetric)
   ```

2. **Instrument code**:
   ```go
   myMetric.Inc()
   ```

3. **Update METRICS.md**

### Modify CRD

1. **Edit CRD** (`operator/config/crd/asya.io_asyas.yaml`)

2. **Apply CRD**:
   ```bash
   kubectl apply -f operator/config/crd/
   ```

3. **Update examples** (`examples/asyas/`)

4. **Update documentation**

## Next Steps

- [Testing Guide](testing.md) - Test your changes
- [Building Guide](building.md) - Build images
- [Deployment Guide](deployment.md) - Deploy to production
