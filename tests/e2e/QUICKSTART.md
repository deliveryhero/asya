# Asya E2E Tests - Quick Start

Get Asya E2E test environment running locally in 5 minutes.

## Prerequisites

Install these tools if you don't have them:

```bash
# Docker
# See: https://docs.docker.com/get-docker/

# Kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/

# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/

# Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

## Deploy

```bash
# 1. Build images (from project root)
cd ../../
make build-images

# 2. Deploy to Kind
cd tests/e2e
./scripts/deploy.sh

# 3. Run E2E tests
./scripts/test-e2e.sh
```

## Deploy Test Actor

```bash
kubectl apply -f rabbitmq-secret.yaml
kubectl apply -f example-actor.yaml
kubectl get asya -n asya
```

## Access Services

```bash
# RabbitMQ Management UI
kubectl port-forward -n asya svc/asya-rabbitmq 15672:15672
# Open http://localhost:15672 (user: asya, pass: asya-password)

# Gateway
kubectl port-forward -n asya svc/asya-gateway 8080:80
# Access at http://localhost:8080
```

## Cleanup

```bash
# Remove components only
./scripts/cleanup.sh

# Remove everything including cluster
./scripts/cleanup.sh --cluster
```

## Troubleshooting

### Pods not starting?
```bash
kubectl get events -n asya --sort-by='.lastTimestamp'
kubectl describe pod <pod-name> -n asya
```

### Images not loading?
```bash
# Reload images
kind load docker-image asya-operator:latest --name asya-kind
kind load docker-image asya-gateway:latest --name asya-kind
kind load docker-image asya-sidecar:latest --name asya-kind
kind load docker-image asya-runtime:latest --name asya-kind
```

### Need fresh start?
```bash
./scripts/cleanup.sh --cluster
./scripts/deploy.sh
```

## What's Next?

- Read the full [README.md](README.md) for detailed documentation
- Explore [example actors](../asyas/)
- Learn about [Asya architecture](../../README.md)
