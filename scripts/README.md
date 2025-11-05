# Scripts

Automation scripts for building, testing, and developing Asya.

## Build & Deploy

### `build-images.sh`

Build Docker images for all Asya components.

```bash
# Build all images locally
./scripts/build-images.sh

# Build for specific platform
./scripts/build-images.sh --platform linux/arm64

# Build and push to registry
./scripts/build-images.sh --push --registry docker.io/myuser --tag v1.0.0

# Options
--tag TAG          Image tag (default: latest)
--registry REG     Registry prefix (e.g., docker.io/myuser)
--platform PLAT    Target platform (default: linux/amd64)
--push             Push images to registry after building
```

Builds:
- `asya-operator` - Kubernetes operator
- `asya-gateway` - MCP gateway
- `asya-sidecar` - Actor sidecar
- `asya-runtime` - Actor runtime base

### `load-images-minikube.sh`

Load Docker images into Minikube for local development.

```bash
# Build and load images
./scripts/load-images-minikube.sh --build

# Load existing images
./scripts/load-images-minikube.sh --tag latest

# Options
--build            Build images before loading
--tag TAG          Image tag to load (default: latest)
```

## Testing

### `test-integration.sh`

Run integration tests using Docker Compose.

```bash
./scripts/test-integration.sh
```

Requires Docker and Docker Compose.

## Port Forwarding (Development)

### `port-forward-grafana.sh`

Port-forward Grafana for metrics visualization and dashboards.

```bash
# Default port (3000)
./scripts/port-forward-grafana.sh

# Custom port
./scripts/port-forward-grafana.sh 8080
```

Features:
- Auto-displays admin credentials
- Grafana UI with pre-configured Prometheus data source
- Actor metrics dashboards

**Note**: Prometheus is accessed internally by Grafana, no separate port-forward needed.

For other services (RabbitMQ Management, Asya Gateway), use kubectl directly:
```bash
# RabbitMQ Management UI
kubectl port-forward -n asya svc/rabbitmq 15672:15672

# Asya Gateway (MCP API)
kubectl port-forward -n asya svc/asya-gateway 8080:8080
```

## Usage Examples

**Full local development setup**:
```bash
# 1. Build images
./scripts/build-images.sh --platform linux/arm64

# 2. Load into Minikube
minikube image load asya-operator:latest asya-gateway:latest asya-sidecar:latest

# 3. Deploy framework
cd examples/deployment-minikube
./deploy.sh

# 4. Port-forward services
cd ../..
./scripts/port-forward-services.sh
```

**Quick rebuild and reload**:
```bash
# Rebuild specific image
docker build --platform linux/arm64 -t asya-operator:latest operator/

# Reload into Minikube
minikube image load asya-operator:latest

# Restart deployment
kubectl rollout restart deployment -n asya-system asya-operator
```

**Access metrics**:
```bash
# Start Grafana port-forward
./scripts/port-forward-grafana.sh

# Open in browser: http://localhost:3000
# Prometheus is accessible via Grafana's data source
```
