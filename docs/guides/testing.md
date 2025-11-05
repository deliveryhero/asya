# Testing Guide

Guide for testing Asya framework and actors.

> 📄 **Tests**: [`tests/`](../../tests/), [`examples/`](../../examples/)
> 📖 **Scripts**: [`scripts/README.md`](../../scripts/README.md)

## Automated Testing

### Full Deployment Test Suite

Run complete test suite (deploy + verify + cleanup):

```bash
cd examples
./run-all-tests.sh
```

This tests:
- Minikube deployment
- Framework components
- Example actors
- Infrastructure integration

**Options:**
```bash
# Skip deployment (test existing)
./run-all-tests.sh --skip-deploy

# Skip actor tests
./run-all-tests.sh --skip-actors

# Cleanup only
./run-all-tests.sh --cleanup-only
```

### Individual Test Suites

**Deployment test:**
```bash
cd examples/deployment-minikube
./deploy.sh
./test-e2e.sh
```

**Actor tests:**
```bash
cd examples
./test-actors.sh
```

**Integration tests:**
```bash
./scripts/test-integration.sh
```

## Unit Testing

### Go Components

**Operator:**
```bash
cd operator
make test

# With coverage
go test ./... -coverprofile=coverage.out
go tool cover -html=coverage.out
```

**Sidecar:**
```bash
cd src/asya-sidecar
go test ./... -v

# Specific package
go test ./internal/router -v
```

**Gateway:**
```bash
cd src/asya-gateway
go test ./... -v

# With race detector
go test ./... -race
```

### Python Components

**Runtime** (requires uv):
```bash
cd src/asya-runtime
uv run pytest tests/ -v

# With coverage
uv run pytest tests/ --cov=asya_actor_runtime --cov-report=html
```

### Using Makefile (Recommended)

Run unit tests for all or specific components:

```bash
# All components
make test-unit

# Specific components
make test-unit-sidecar    # Go sidecar only
make test-unit-gateway    # Go gateway only
make test-unit-runtime    # Python runtime only
```

## Integration Testing

### Using Makefile (Recommended)

```bash
# All integration tests
make test-integration

# Specific integration tests
make test-integration-sidecar   # E2E: Sidecar ↔ Runtime via RabbitMQ
make test-integration-gateway   # E2E: Gateway ↔ Actors via RabbitMQ
```

### Via Script (Legacy)

```bash
./scripts/test-integration.sh
```

Tests full message flow:
1. RabbitMQ setup
2. Sidecar communication
3. Runtime processing
4. Message routing

### Kubernetes Tests

```bash
cd examples/deployment-minikube
./test-e2e.sh
```

Verifies:
- All pods running
- Services accessible
- CRDs installed
- Operators healthy

## Testing Actors

### Test Simple Actor

```bash
# Deploy actor
kubectl apply -f examples/asyas/simple-actor.yaml

# Check status
kubectl get asyas simple-actor
kubectl describe asya simple-actor

# Check deployment
kubectl get deployment simple-actor
kubectl get pods -l app=simple-actor

# Check logs
kubectl logs -l app=simple-actor -c sidecar
kubectl logs -l app=simple-actor -c runtime
```

### Test Autoscaling

```bash
# Deploy actor with scaling
kubectl apply -f examples/asyas/simple-actor.yaml

# Check initial state (should be 0 replicas)
kubectl get deployment simple-actor
kubectl get hpa

# Send messages to queue
kubectl exec -n asya deploy/rabbitmq -- rabbitmqadmin publish \
  exchange=asya \
  routing_key=simple-queue \
  payload='{"route":{"steps":["simple-queue"],"current":0},"payload":{"test":true}}'

# Watch scaling
watch kubectl get deployment simple-actor
watch kubectl get hpa

# Check ScaledObject
kubectl get scaledobject simple-actor -o yaml
```

### Test Message Flow

```bash
# Deploy 3-step pipeline
cat <<EOF | kubectl apply -f -
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: pipeline-test
spec:
  queueName: step1
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: runtime
          image: asya-runtime:latest
          env:
          - name: ASYA_PROCESS_MODULE
            value: "echo_handler:process"
---
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: pipeline-test-2
spec:
  queueName: step2
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: runtime
          image: asya-runtime:latest
          env:
          - name: ASYA_PROCESS_MODULE
            value: "echo_handler:process"
EOF

# Send message
kubectl exec -n asya deploy/rabbitmq -- rabbitmqadmin publish \
  exchange=asya \
  routing_key=step1 \
  payload='{"route":{"steps":["step1","step2"],"current":0},"payload":{"msg":"test"}}'

# Monitor queues
kubectl exec -n asya deploy/rabbitmq -- rabbitmqctl list_queues
```

## Testing Gateway

### Health Check

```bash
kubectl port-forward -n asya svc/asya-gateway 8080:8080
curl http://localhost:8080/health
```

### Create Job

```bash
# MCP request
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "process",
      "arguments": {
        "input": "test data"
      }
    },
    "id": 1
  }'
```

### Monitor Job

```bash
# Get job status
curl http://localhost:8080/jobs/<job-id>

# Stream updates
curl http://localhost:8080/jobs/<job-id>/stream
```

## Manual Testing

### Test Runtime Socket

```bash
# Create test runtime
cat > test_asya_runtime.py <<'EOF'
import socket
import json

def process(payload):
    return {"result": f"Processed: {payload}"}

sock = socket.socket(socket.AF_UNIX)
sock.bind("/tmp/test.sock")
sock.listen(1)

while True:
    conn, _ = sock.accept()
    data = conn.recv(1024)
    payload = json.loads(data)
    result = process(payload)
    response = json.dumps({"status": "ok", "result": result})
    conn.sendall(response.encode())
    conn.close()
EOF

python test_asya_runtime.py &

# Test with sidecar
export ASYA_SOCKET_PATH=/tmp/test.sock
export ASYA_QUEUE_NAME=test-queue
./bin/sidecar
```

### Test Queue Integration

```bash
# Start RabbitMQ locally
docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management

# Create queue
docker exec rabbitmq rabbitmqadmin declare queue name=test-queue durable=true

# Send message
docker exec rabbitmq rabbitmqadmin publish \
  exchange=amq.default \
  routing_key=test-queue \
  payload='{"route":{"steps":["test-queue"],"current":0},"payload":{"test":true}}'

# Check queue
docker exec rabbitmq rabbitmqctl list_queues
```

## Performance Testing

### Load Testing

```bash
# Install tools via uv
uv pip install locust

# Create load test
cat > locustfile.py <<'EOF'
from locust import HttpUser, task, between

class GatewayUser(HttpUser):
    wait_time = between(1, 2)

    @task
    def create_job(self):
        self.client.post("/mcp", json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "process", "arguments": {"data": "test"}},
            "id": 1
        })
EOF

# Run load test
locust -f locustfile.py --host http://localhost:8080
```

### Stress Testing

```bash
# Flood queue with messages
for i in {1..1000}; do
  kubectl exec -n asya deploy/rabbitmq -- rabbitmqadmin publish \
    exchange=asya \
    routing_key=test-queue \
    payload="{\"route\":{\"steps\":[\"test-queue\"],\"current\":0},\"payload\":{\"id\":$i}}"
done

# Monitor scaling and performance
watch kubectl get hpa
watch kubectl get deployment
kubectl top pods
```

## Debugging

### Check Logs

```bash
# Operator logs
kubectl logs -n asya-system -l app=asya-operator -f

# Gateway logs
kubectl logs -n asya -l app=asya-gateway -f

# Actor logs
kubectl logs -l app=my-actor -c sidecar -f
kubectl logs -l app=my-actor -c runtime -f

# RabbitMQ logs
kubectl logs -n asya -l app=rabbitmq -f
```

### Describe Resources

```bash
# AsyncActor resource
kubectl describe asya my-actor

# Deployment
kubectl describe deployment my-actor

# ScaledObject
kubectl describe scaledobject my-actor

# Pods
kubectl describe pod <pod-name>
```

### Check Events

```bash
# All events
kubectl get events --sort-by='.lastTimestamp'

# For specific resource
kubectl get events --field-selector involvedObject.name=my-actor
```

## Common Issues

### Actor Not Scaling

```bash
# Check KEDA
kubectl get scaledobject my-actor -o yaml
kubectl logs -n keda -l app=keda-operator

# Check queue
kubectl exec -n asya deploy/rabbitmq -- rabbitmqctl list_queues

# Check HPA
kubectl get hpa
kubectl describe hpa keda-hpa-my-actor
```

### Messages Not Processing

```bash
# Check sidecar logs
kubectl logs -l app=my-actor -c sidecar

# Check runtime logs
kubectl logs -l app=my-actor -c runtime

# Check queue bindings
kubectl exec -n asya deploy/rabbitmq -- rabbitmqctl list_bindings
```

### Socket Errors

```bash
# Check volume mounts
kubectl get pod <pod-name> -o yaml | grep -A 10 volumeMounts

# Check permissions
kubectl exec <pod-name> -c runtime -- ls -la /tmp/sockets

# Check socket file
kubectl exec <pod-name> -c sidecar -- ls -la /tmp/sockets
```

## Next Steps

- [Development Guide](development.md) - Local development
- [Deployment Guide](deployment.md) - Production deployment
- [Building Guide](building.md) - Build custom images
