# Onboarding Guide

Guide for integrating Asya🎭 into your project.

## Should I Use Asya🎭?

Asya🎭 is designed for **async AI workloads** that need:

✅ **Good fit**:
- Multi-step AI pipelines (preprocessing → inference → postprocessing)
- Bursty workloads with unpredictable traffic patterns
- Cost optimization through scale-to-zero
- GPU-intensive tasks requiring independent scaling
- Resilient processing with automatic retries
- Kubernetes-native deployments

❌ **Not a good fit**:
- Synchronous request-response APIs (use HTTP services instead)
- Sub-second latency requirements (queue overhead adds ~100-500ms)
- Simple single-step processing (overhead may not be worth it)
- Stateful workflows requiring session affinity

## Architecture Decision

**Before adopting Asya🎭**, understand the trade-offs:

### Asya🎭 (Async Actors)
- **Pro**: Independent scaling, fault tolerance, cost efficiency
- **Pro**: Easy to add/remove/reorder pipeline steps
- **Pro**: KEDA autoscaling with scale-to-zero
- **Con**: Added latency from queuing (~100-500ms per hop)
- **Con**: Eventual consistency (not immediate results)
- **Con**: Additional infrastructure (message queue, operator)

### Traditional HTTP Services
- **Pro**: Lower latency, simpler debugging
- **Pro**: Synchronous responses
- **Con**: Coupled scaling, client orchestration burden
- **Con**: Poor handling of traffic spikes
- **Con**: No scale-to-zero

See [Architecture Motivation](../architecture/README.md#motivation) for detailed comparison.

## Prerequisites

### Infrastructure Requirements

**Kubernetes cluster:**
- Version 1.23+
- kubectl configured and authenticated
- Cluster admin access (for CRD installation)

**Message transport** (choose one):
- RabbitMQ 3.8+ (recommended for OSS deployments)
- AWS SQS (for AWS-native deployments)

**Optional but recommended:**
- KEDA 2.0+ (for autoscaling)
- PostgreSQL 12+ (if using MCP Gateway for job tracking)
- MinIO or S3 (for result persistence via happy-end actor)
- Prometheus + Grafana (for observability)

### Development Tools

**Required:**
- Helm 3.0+ (for operator installation)
- Docker (for building custom runtime images)

**Optional:**
- `uv` (Python package manager, for runtime development)
- Go 1.23+ (if modifying sidecar/operator)
- `kubectl krew` plugins: `ctx`, `ns`, `tail`

### Project Readiness

**Code structure:**
- Python handler functions for processing logic
- Handlers should be stateless or handle their own state
- No assumptions about execution order across pipeline steps

**Example handler:**
```python
def process(payload: dict) -> dict:
    """
    Process a single payload.

    Args:
        payload: Input data from previous actor

    Returns:
        Processed result for next actor
    """
    result = your_ai_model.predict(payload)
    return {"prediction": result}
```

**Deployment artifacts:**
- Dockerfile for runtime container
- AsyncActor YAML manifests
- ConfigMaps/Secrets for configuration

## AsyncActor Specification

AsyncActor is a Kubernetes Custom Resource that defines:

### Minimal Example
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
  namespace: default
spec:
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
          image: my-runtime:latest
          env:
          - name: ASYA_HANDLER
            value: "my_module.process"
```

### Key Fields

**transport** (required):
- References transport configured in operator Helm values
- Common values: `rabbitmq`, `sqs`
- Transport config (host, credentials) is NOT in AsyncActor CRD

**scaling** (optional but recommended):
- `enabled: true` - Enable KEDA autoscaling
- `minReplicas: 0` - Scale to zero when queue is empty
- `maxReplicas: N` - Cap maximum replicas
- `queueLength: M` - Target messages per replica

**workload** (required):
- `type: Deployment` or `StatefulSet`
- `template.spec` - Standard Kubernetes pod spec
- Runtime container must expose Unix socket handler

**Runtime environment variables:**
- `ASYA_HANDLER` - Python handler (e.g., `module.Class.method` or `module.function`)
- `ASYA_HANDLER_MODE` - `payload` (default) or `envelope`
- `ASYA_SOCKETS_DIR` - Socket directory (default: `/tmp/sockets`)

See [AsyncActor CRD Reference](../architecture/asya-operator.md#asyncactor-crd-api-reference) for complete specification.

## Actor Behavior

### Message Flow

```
Queue → Sidecar → Runtime → Sidecar → Next Queue
```

1. **Sidecar pulls** message from actor's queue (e.g., `my-actor`)
2. **Sidecar forwards** payload to runtime via Unix socket
3. **Runtime processes** and returns result
4. **Sidecar routes** result to next queue based on `route.current`
5. **Sidecar acknowledges** original message

### Automatic Routing

**End-of-pipeline routing** (automatic):
- When `route.current` reaches end of `actors` array → routes to `happy-end` queue
- When errors occur → routes to `error-end` queue
- **Never include `happy-end` or `error-end` in route configurations**

**Example route progression:**
```json
// Initial envelope
{
  "id": "abc123",
  "route": {"actors": ["preprocess", "inference"], "current": 0},
  "payload": {"text": "Hello"}
}

// After preprocess actor
{
  "id": "abc123",
  "route": {"actors": ["preprocess", "inference"], "current": 1},
  "payload": {"tokens": [1, 2, 3]}
}

// After inference actor (no more actors, routes to happy-end automatically)
{
  "id": "abc123",
  "route": {"actors": ["preprocess", "inference"], "current": 2},
  "payload": {"result": "greeting"}
}
```

### Scaling Behavior

**KEDA autoscaling** (when enabled):
- Monitors queue depth every `pollingInterval` seconds (default: 10s)
- Scales up when `queue_length > queueLength * current_replicas`
- Scales down after `cooldownPeriod` (default: 60s) of low traffic
- Can scale to zero when queue is empty (if `minReplicas: 0`)

**Cold start:**
- Scale from 0 to 1 takes ~10-30 seconds (pod startup time)
- Subsequent scale-ups are faster (~5-10 seconds)
- Plan for cold start latency in user experience

**Example scaling timeline:**
```
t=0s:   0 replicas, 100 messages arrive
t=10s:  KEDA detects messages, scales to 1 replica
t=30s:  Pod starts, begins processing
t=40s:  KEDA sees 95 messages remaining, scales to 19 replicas
t=50s:  All pods processing, queue drains
t=5m:   Queue empty for 1 minute, scales back to 0
```

### Error Handling

**Automatic retry:**
- Transport-level NACK triggers redelivery
- Exponential backoff managed by message queue
- After max retries, message goes to dead-letter queue

**Error routing:**
- Runtime errors route to `error-end` queue
- `error-end` crew actor handles retry logic and DLQ management
- Errors reported to gateway (if using MCP integration)

**Timeout behavior:**
- `timeout.processing` (default: 300s) - Max processing time per message
- After timeout, sidecar sends error to `error-end` queue
- Pod may be killed if graceful shutdown exceeds `timeout.gracefulShutdown`

## Integration Patterns

### Pattern 1: API Gateway → Actor Pipeline

**Use case:** External API triggers multi-step AI processing

```
HTTP Client → MCP Gateway → Actor 1 → Actor 2 → happy-end (S3)
                ↓ (SSE stream)
         Real-time status updates
```

**Setup:**
1. Deploy MCP Gateway with PostgreSQL for envelope tracking
2. Configure gateway tools to create envelopes with routes
3. Deploy actor pipeline (Actor 1, Actor 2, happy-end)
4. Client calls gateway API, receives SSE stream for status

**Example:**
```bash
# Client submits job
curl -X POST http://gateway/mcp/tools/call \
  -d '{"tool":"process_image","params":{"url":"..."}}'

# Gateway creates envelope with route: ["resize", "classify"]
# Client receives SSE stream with status updates
```

### Pattern 2: Direct Queue Injection

**Use case:** Existing system already has message queue

```
Your System → RabbitMQ → Actor 1 → Actor 2 → happy-end
```

**Setup:**
1. Deploy only Asya🎭 operator (no gateway)
2. Your system publishes envelopes to first actor's queue
3. Actors process and route through pipeline

**Example:**
```python
# Your existing code
import pika

envelope = {
    "id": "job-123",
    "route": {"actors": ["preprocess", "inference"], "current": 0},
    "payload": {"image_url": "https://..."}
}

channel.basic_publish(
    exchange='',
    routing_key='preprocess',  # First actor's queue
    body=json.dumps(envelope)
)
```

### Pattern 3: Hybrid (Mix Actors with HTTP Services)

**Use case:** Some steps need async actors, others need HTTP

```
HTTP Service → Actor (GPU inference) → HTTP Service (storage)
```

**Setup:**
1. Actor returns result with modified route
2. Next "actor" is actually an HTTP adapter that calls your service
3. HTTP adapter publishes next envelope or terminates

**Note:** Requires custom adapter actor to bridge HTTP services.

## Common Gotchas

**Queue naming:**
- Actor name automatically becomes queue name
- Use lowercase, alphanumeric, hyphens only (DNS-1123 compliant)
- Example: `text-processor` creates queue `text-processor`

**Handler mode confusion:**
- `payload` mode (default): Handler only sees payload, sidecar manages routing
- `envelope` mode: Handler sees full envelope, must preserve route history
- **Use `payload` mode unless you need custom routing logic**

**Transport configuration:**
- Transport config is in operator Helm values, not AsyncActor CRD
- Changing transport requires operator redeployment
- Actors only reference transport by name

**Sidecar injection:**
- Operator automatically injects sidecar container
- Don't manually add sidecar to workload template
- Sidecar shares socket volume with runtime

**End routing:**
- Never add `happy-end` or `error-end` to routes
- Sidecar handles this automatically
- Custom end actors use `ASYA_STEP_HAPPY_END` env var in sidecar config

## Next Steps

- [Installation Guide](03-installation.md) - Set up Kubernetes cluster and operator
- [Core Concepts](02-concepts.md) - Deep dive into actors, envelopes, routing
- [AsyncActor CRD Reference](../architecture/asya-operator.md#asyncactor-crd-api-reference) - Complete YAML specification
- [Quick Start](04-quickstart.md) - Deploy your first actor
