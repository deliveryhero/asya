# Asya E2E Tests

End-to-end tests for Asya framework using Kind (Kubernetes in Docker).

## Overview

This deployment includes:

- **Infrastructure**:
  - RabbitMQ for message queuing
  - Prometheus for metrics collection
  - Grafana for visualization
  - KEDA for event-driven autoscaling

- **Asya Framework**:
  - Asya Operator (CRD controller)
  - Asya Gateway (MCP JSON-RPC server with PostgreSQL)

- **Test Actors**:
  - test-echo: Simple echo handler
  - test-progress: Progress streaming handler
  - test-doubler: Pipeline step 1 (doubles value)
  - test-incrementer: Pipeline step 2 (adds 5)
  - test-error: Error handling test
  - test-timeout: Timeout handling test

## Prerequisites

Required tools:
- [Kind](https://kind.sigs.k8s.io/) v0.20.0+
- [kubectl](https://kubernetes.io/docs/tasks/tools/) v1.28+
- [Helm](https://helm.sh/) v3.12+
- [Helmfile](https://github.com/helmfile/helmfile) v0.157+
- [Docker](https://www.docker.com/) v24+

## Quick Start

1. **Deploy the cluster** (creates cluster, builds images, deploys everything):
   ```bash
   ./scripts/deploy.sh
   ```
   This takes approximately 5-10 minutes.

   If the cluster already exists, it will be reused. To force recreation:
   ```bash
   ./scripts/deploy.sh --recreate
   ```

2. **Run E2E tests**:
   ```bash
   ./scripts/test-e2e.sh
   ```

3. **Clean up**:
   ```bash
   ./scripts/cleanup.sh
   ```

## Accessing Services

Services are exposed via NodePort:

- **Gateway** (MCP): http://localhost:8080
- **Grafana**: http://localhost:3000 (admin/admin)

To access RabbitMQ Management UI:
```bash
kubectl port-forward -n asya svc/asya-rabbitmq 15672:15672
# Then visit: http://localhost:15672 (guest/guest)
```

## Testing

### Helm Tests

The deployment includes Helm tests that validate core functionality:

**Operator tests**:
- Operator deployment readiness
- AsyncActor CRD installation

**Gateway tests**:
- Health endpoint (`/health`)
- MCP tools endpoint (`/tools/list`)

Run Helm tests manually:
```bash
# Test operator
helm test asya-operator -n asya-system --logs

# Test gateway
helm test asya-gateway -n asya --logs
```

Helm tests run automatically during `./scripts/deploy.sh`.

### E2E Tests

The E2E tests (`tests/e2e/`) validate the complete framework functionality:

- **test_e2e_gateway.py**: Basic MCP tool calls, job status, SSE streaming
- **test_e2e_progress.py**: Progress tracking through multi-step pipelines
- **test_e2e_messaging.py**: Message routing and error handling

Run tests:
```bash
./scripts/test-e2e.sh
```

Or manually:
```bash
export ASYA_GATEWAY_URL=http://localhost:8080
export RABBITMQ_MGMT_URL=http://localhost:15672
kubectl port-forward -n asya svc/asya-rabbitmq 15672:15672 &
uv run pytest -v tests/e2e/
```

### Manual Testing

Test MCP tool call:
```bash
curl -X POST http://localhost:8080/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name": "test_echo", "arguments": {"message": "Hello Asya!"}}'
```

Check job status (replace JOB_ID):
```bash
curl http://localhost:8080/jobs/JOB_ID
```

Stream job progress via SSE (replace JOB_ID):
```bash
curl -N http://localhost:8080/jobs/JOB_ID/stream
```

## Development

### Rebuilding Images

After making code changes:
```bash
# Build images
cd ../../..  # Root directory
make build-images

# Load into Kind
kind load docker-image asya-operator:latest --name asya-kind
kind load docker-image asya-gateway:latest --name asya-kind
kind load docker-image asya-sidecar:latest --name asya-kind
kind load docker-image asya-runtime:latest --name asya-kind

# Restart deployments
kubectl rollout restart deployment -n asya-system asya-operator
kubectl rollout restart deployment -n asya asya-gateway
kubectl rollout restart deployment -n asya test-echo test-progress test-doubler test-incrementer test-error test-timeout
```

### Viewing Logs

Gateway logs:
```bash
kubectl logs -n asya -l app.kubernetes.io/name=asya-gateway -f
```

Actor logs (replace ACTOR_NAME):
```bash
kubectl logs -n asya -l asya.dev/name=ACTOR_NAME -c sidecar -f
kubectl logs -n asya -l asya.dev/name=ACTOR_NAME -c runtime -f
```

Operator logs:
```bash
kubectl logs -n asya-system -l control-plane=controller-manager -f
```

### Debugging

Check actor deployment status:
```bash
kubectl get asyas -n asya
kubectl get pods -n asya
kubectl get deployments -n asya
```

Check RabbitMQ queues:
```bash
kubectl port-forward -n asya svc/asya-rabbitmq 15672:15672
# Visit http://localhost:15672
```

Check KEDA scaling:
```bash
kubectl get scaledobject -n asya
kubectl get hpa -n asya
```

## Architecture

### Message Flow

1. **Client** → POST /tools/call → **Gateway**
2. **Gateway** creates job, sends message to first queue
3. **Actor Sidecar** consumes message from queue
4. **Sidecar** forwards payload to **Runtime** via Unix socket
5. **Runtime** executes user function
6. **Sidecar** routes response to next queue (or terminal queue)
7. **Terminal actors** (happy-end/error-end) report final status to Gateway

### Autoscaling

All test actors use KEDA with RabbitMQ triggers:
- **Min replicas**: 1
- **Max replicas**: 3
- **Scale threshold**: 5 messages in queue

Watch scaling in action:
```bash
kubectl get hpa -n asya -w
```

## Configuration

### Gateway Routes

Test tool routes are defined in `manifests/00-configmaps.yaml` (gateway-routes ConfigMap).

To add new tools, edit the ConfigMap and restart the gateway:
```bash
kubectl edit configmap -n asya gateway-routes
kubectl rollout restart deployment -n asya asya-gateway
```

### Test Handlers

Test handler implementations are in `manifests/00-configmaps.yaml` (test-handlers ConfigMap).

To modify handlers:
1. Edit the ConfigMap
2. Restart actor deployments
```bash
kubectl edit configmap -n asya test-handlers
kubectl rollout restart deployment -n asya test-echo test-progress test-doubler test-incrementer test-error test-timeout
```

## Troubleshooting

### Cluster won't start

```bash
# Delete and recreate
kind delete cluster --name asya-kind
./scripts/deploy.sh
```

### Images not loading

```bash
# Check if images exist
docker images | grep asya

# Rebuild if needed
cd ../../..
make build-images

# Load into Kind
kind load docker-image asya-operator:latest --name asya-kind
kind load docker-image asya-gateway:latest --name asya-kind
kind load docker-image asya-sidecar:latest --name asya-kind
kind load docker-image asya-runtime:latest --name asya-kind
```

### Actors not starting

```bash
# Check operator logs
kubectl logs -n asya-system -l control-plane=controller-manager

# Check actor pod events
kubectl describe pod -n asya <pod-name>

# Check if CRDs are installed
kubectl get crd | grep asya
```

### Tests failing

```bash
# Check gateway health
curl http://localhost:8080/health

# Check RabbitMQ consumers
kubectl port-forward -n asya svc/asya-rabbitmq 15672:15672
# Visit http://localhost:15672 and check Queues tab

# Check actor logs
kubectl logs -n asya -l asya.dev/name=test-echo -c sidecar
```

## Resource Usage

Typical resource usage for the complete stack:
- **CPU**: ~2 cores
- **Memory**: ~4 GB
- **Disk**: ~10 GB

Adjust resource limits in `helmfile.yaml` if needed.
