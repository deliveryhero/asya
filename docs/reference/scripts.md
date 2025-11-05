# Scripts Reference

Automation scripts for building, testing, and deploying Asya.

> 📄 **Scripts**: [`scripts/`](../../scripts/)
> 📖 **Scripts README**: [`scripts/README.md`](../../scripts/README.md)

## Build Scripts

### build-images.sh

Build Docker images for all Asya components.

**Usage:**
```bash
./scripts/build-images.sh [OPTIONS]
```

**Options:**
- `--tag TAG` - Image tag (default: `latest`)
- `--registry REG` - Registry prefix (e.g., `docker.io/myuser`)
- `--platform PLAT` - Target platform (default: `linux/amd64`)
- `--push` - Push images to registry after building

**Examples:**
```bash
# Build all images locally
./scripts/build-images.sh

# Build for ARM64
./scripts/build-images.sh --platform linux/arm64

# Build and push to Docker Hub
./scripts/build-images.sh --push --registry docker.io/myuser --tag v1.0.0
```

**Builds:**
- `asya-operator`
- `asya-gateway`
- `asya-sidecar`
- `asya-runtime`

### load-images-minikube.sh

Load Docker images into Minikube for local development.

**Usage:**
```bash
./scripts/load-images-minikube.sh [OPTIONS]
```

**Options:**
- `--build` - Build images before loading
- `--tag TAG` - Image tag to load (default: `latest`)

**Examples:**
```bash
# Build and load all images
./scripts/load-images-minikube.sh --build

# Load existing images with specific tag
./scripts/load-images-minikube.sh --tag v1.0.0
```

## Test Scripts

### test-integration.sh

Run integration tests using Docker Compose.

**Usage:**
```bash
./scripts/test-integration.sh
```

**Requirements:**
- Docker
- Docker Compose

**Tests:**
- Full message flow
- RabbitMQ integration
- Sidecar ↔ Runtime communication
- Message routing

## Utility Scripts

### port-forward-grafana.sh

Port-forward Grafana for metrics visualization.

**Usage:**
```bash
./scripts/port-forward-grafana.sh [ASYA_GATEWAY_PORT]
```

**Arguments:**
- `ASYA_GATEWAY_PORT` - Local port (default: `3000`)

**Examples:**
```bash
# Default port (3000)
./scripts/port-forward-grafana.sh

# Custom port
./scripts/port-forward-grafana.sh 8080
```

**Features:**
- Auto-displays admin credentials
- Opens access to Grafana UI
- Prometheus data source pre-configured
- Actor metrics dashboards available

**Accessing Other Services:**

RabbitMQ Management:
```bash
kubectl port-forward -n asya svc/rabbitmq 15672:15672
# http://localhost:15672
```

Asya Gateway:
```bash
kubectl port-forward -n asya svc/asya-gateway 8080:8080
# http://localhost:8080/health
```

PostgreSQL:
```bash
kubectl port-forward -n asya svc/postgresql 5432:5432
# psql -h localhost -U asya
```

## Usage Examples

### Development Workflow

```bash
# 1. Build all images
./scripts/build-images.sh --tag dev

# 2. Load into Minikube
./scripts/load-images-minikube.sh --tag dev

# 3. Deploy framework
cd examples/deployment-minikube
./deploy.sh

# 4. Access services
../../scripts/port-forward-grafana.sh
```

### Production Build

```bash
# Build for multiple platforms and push
./scripts/build-images.sh \
  --platform linux/amd64,linux/arm64 \
  --registry docker.io/myorg \
  --tag v1.2.3 \
  --push
```

### Quick Rebuild

```bash
# Rebuild specific component
cd src/asya-sidecar
docker build -t asya-sidecar:dev .

# Load into Minikube
minikube image load asya-sidecar:dev

# Restart deployment
kubectl rollout restart deployment my-actor
```

## Next Steps

- [Building Guide](../guides/building.md) - Detailed build instructions
- [Testing Guide](../guides/testing.md) - Testing strategies
- [Development Guide](../guides/development.md) - Local development
