# Building Images

Guide for building Asya component images.

> 📄 **Scripts**: [`scripts/`](../../scripts/)
> 📖 **Scripts README**: [`scripts/README.md`](../../scripts/README.md)

## Quick Start

### Automated Build (Recommended)

Build all framework images:

```bash
./scripts/build-images.sh
```

This builds:
- `asya-operator` - Kubernetes operator
- `asya-gateway` - MCP gateway
- `asya-sidecar` - Actor sidecar
- `asya-runtime` - Actor runtime base

### Build Options

```bash
# Build for specific platform
./scripts/build-images.sh --platform linux/arm64

# Build and push to registry
./scripts/build-images.sh --push --registry docker.io/myuser --tag v1.0.0

# Build with custom tag
./scripts/build-images.sh --tag dev-20241006
```

**Available options:**
- `--tag TAG` - Image tag (default: `latest`)
- `--registry REG` - Registry prefix (e.g., `docker.io/myuser`)
- `--platform PLAT` - Target platform (default: `linux/amd64`)
- `--push` - Push images to registry after building

## Building Individual Components

### Asya Operator

```bash
cd operator

# Build binary
make build

# Build Docker image
make docker-build IMG=asya-operator:dev

# Build and push
make docker-build docker-push IMG=docker.io/myuser/asya-operator:v1.0.0
```

### Asya Gateway

```bash
cd src/asya-gateway

# Build binary
go build -o bin/gateway ./cmd/gateway

# Build Docker image
docker build -t asya-gateway:dev .

# Multi-platform build
docker buildx build --platform linux/amd64,linux/arm64 -t asya-gateway:dev .
```

### Asya Sidecar

```bash
cd src/asya-sidecar

# Build binary
go build -o bin/sidecar ./cmd/sidecar

# Or use Makefile
make build

# Build Docker image
docker build -t asya-sidecar:dev .
```

### Asya Runtime

```bash
cd src/asya-runtime

# Build Docker image (Python-based)
docker build -t asya-runtime:dev .
```

## Local Development with Minikube

### Load Images into Minikube

```bash
# Build and load all images
./scripts/load-images-minikube.sh --build

# Load existing images
./scripts/load-images-minikube.sh --tag latest

# Load specific tag
./scripts/load-images-minikube.sh --tag v1.0.0
```

### Manual Load

```bash
# Build images first
./scripts/build-images.sh --tag dev

# Load into Minikube
minikube image load asya-operator:dev
minikube image load asya-gateway:dev
minikube image load asya-sidecar:dev
minikube image load asya-runtime:dev

# Verify
minikube image ls | grep asya
```

### Rebuild and Reload Workflow

```bash
# Quick rebuild of one component
cd src/asya-sidecar
docker build -t asya-sidecar:dev .

# Load into Minikube
minikube image load asya-sidecar:dev

# Restart deployment to use new image
kubectl rollout restart deployment -n default my-actor
```

## Building for Production

### Multi-Platform Builds

```bash
# Set up buildx (one time)
docker buildx create --name multiplatform --use

# Build for multiple platforms
./scripts/build-images.sh \
  --platform linux/amd64,linux/arm64 \
  --registry docker.io/myuser \
  --tag v1.0.0 \
  --push
```

### Versioning Strategy

**Development:**
```bash
./scripts/build-images.sh --tag dev-$(date +%Y%m%d)
```

**Release:**
```bash
./scripts/build-images.sh --tag v1.2.3 --push --registry docker.io/myorg
```

**Latest:**
```bash
./scripts/build-images.sh --tag latest --push --registry docker.io/myorg
```

## Image Optimization

### Minimize Image Size

**Go components** (operator, gateway, sidecar):
- Use multi-stage builds
- Alpine or distroless base images
- Strip debug symbols

**Python components** (runtime):
- Use slim Python images
- Multi-stage builds
- Only install required dependencies

### Build Cache

Use BuildKit for faster builds:

```bash
export DOCKER_BUILDKIT=1
docker build -t asya-sidecar:dev src/asya-sidecar/
```

## Troubleshooting

### Build Fails on M1/M2 Mac

```bash
# Build for linux/amd64 explicitly
./scripts/build-images.sh --platform linux/amd64
```

### Out of Disk Space

```bash
# Clean up Docker
docker system prune -a

# Remove old Minikube images
minikube ssh -- docker system prune -a
```

### Image Not Found in Minikube

```bash
# Check loaded images
minikube image ls

# Reload image
minikube image load asya-sidecar:latest

# Set imagePullPolicy to Never in deployment
kubectl set image deployment/my-actor sidecar=asya-sidecar:latest
kubectl patch deployment my-actor -p '{"spec":{"template":{"spec":{"containers":[{"name":"sidecar","imagePullPolicy":"Never"}]}}}}'
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Build and Push Images

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Login to Docker Hub
        uses: docker/login-action@v2
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Build and Push
        run: |
          ./scripts/build-images.sh \
            --tag ${GITHUB_REF#refs/tags/} \
            --registry docker.io/myorg \
            --push
```

## Next Steps

- [Deployment Guide](deployment.md) - Deploy built images
- [Testing Guide](testing.md) - Test your builds
- [Development Guide](development.md) - Local development workflow
