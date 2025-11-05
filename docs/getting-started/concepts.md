# Core Concepts

Understanding the key concepts in Asya framework.

## Overview

Asya (**Asy**ncronous **a**ctor) is an async actor-based framework for deploying AI workloads on Kubernetes. It uses a sidecar pattern to handle message routing while your application focuses on processing logic.

## Key Concepts

### Actor

An **Actor** is a computational unit that:
- Receives messages from a queue
- Processes messages independently
- Optionally produces output messages
- Can scale automatically based on queue depth

In Asya, you define actors using the `Asya` Custom Resource Definition (CRD).

### Sidecar Pattern

Each actor pod contains two containers:

1. **Sidecar** (asya-sidecar):
   - Receives messages from queue
   - Routes messages to runtime
   - Handles errors and retries
   - Manages acknowledgments

2. **Runtime** (your application):
   - Processes the actual payload
   - Returns results
   - Focuses purely on business logic

They communicate via Unix socket for high performance and simplicity.

### Message Flow

```
Queue → Sidecar → Runtime → Sidecar → Next Queue
```

1. Sidecar pulls message from queue
2. Sidecar sends payload to runtime via Unix socket
3. Runtime processes and returns result
4. Sidecar routes result to next queue based on route
5. Sidecar acknowledges original message

### Routes

A **route** defines the processing pipeline:

```json
{
  "route": {
    "steps": ["step1", "step2", "step3"],
    "current": 0
  },
  "payload": {...}
}
```

- `steps`: Array of queue names representing the pipeline
- `current`: Index of current step (auto-incremented by sidecar)
- `payload`: The actual data being processed

### Terminal Queues

Two special queues mark the end of processing:

- **happy-end**: Successful completion
- **error-end**: Errors or timeouts

### Transport

The **transport** defines which queue system to use:

- **RabbitMQ**: Topic exchange with auto-declared queues
- ~~**AWS SQS**~~ (support removed in latest version)

### Workload Types

Asya supports three Kubernetes workload types:

1. **Deployment** (default):
   - Stateless actors
   - Horizontal scaling
   - Best for most use cases

2. **StatefulSet**:
   - Requires stable identity
   - Persistent storage
   - Ordered deployment

3. **Job**:
   - One-off processing
   - Batch workloads
   - Completion tracking

### Autoscaling

**KEDA** (Kubernetes Event Driven Autoscaling) integration:

- Monitors queue depth
- Scales actors based on messages waiting
- Can scale to zero when idle
- Fast scale-up for bursty workloads

Configuration:
```yaml
scaling:
  enabled: true
  minReplicas: 0        # Scale to zero when idle
  maxReplicas: 10       # Maximum pod count
  queueLength: 5        # Messages per replica
```

### MCP Gateway

The **MCP Gateway** provides:

- Model Context Protocol (JSON-RPC 2.0) interface
- Job creation and status tracking
- Real-time streaming via Server-Sent Events (SSE)
- PostgreSQL-backed job persistence

Used for client-facing APIs and job management.

## Architecture Components

### Operator

The **Asya Operator** is a Kubernetes controller that:
- Watches `Asya` custom resources
- Injects sidecar containers automatically
- Creates workloads (Deployment/StatefulSet/Job)
- Sets up KEDA autoscaling
- Manages lifecycle

### Runtime Protocol

Communication between sidecar and runtime:

**Request** (sidecar → runtime):
```json
<raw payload bytes>
```

**Success Response** (runtime → sidecar):
```json
{
  "status": "ok",
  "result": <single response or array>
}
```

**Error Response** (runtime → sidecar):
```json
{
  "error": "error_code",
  "message": "description"
}
```

## Data Flow Example

Let's trace a message through a 3-step pipeline:

**Initial Message:**
```json
{
  "route": {
    "steps": ["preprocess", "inference", "postprocess"],
    "current": 0
  },
  "payload": {"text": "Hello world"}
}
```

**Step 1 (preprocess queue):**
1. Sidecar receives from `preprocess` queue
2. Sends `{"text": "Hello world"}` to runtime
3. Runtime returns `{"tokens": [1, 2, 3]}`
4. Sidecar increments `current` to 1
5. Sends to `inference` queue

**Step 2 (inference queue):**
1. Sidecar receives from `inference` queue
2. Sends `{"tokens": [1, 2, 3]}` to runtime
3. Runtime returns `{"prediction": "greeting"}`
4. Sidecar increments `current` to 2
5. Sends to `postprocess` queue

**Step 3 (postprocess queue):**
1. Sidecar receives from `postprocess` queue
2. Sends `{"prediction": "greeting"}` to runtime
3. Runtime returns `{"result": "Classified as greeting"}`
4. No more steps, sends to `happy-end` queue

## Fan-Out Pattern

Runtime can return multiple results for fan-out:

**Runtime Response:**
```json
{
  "status": "ok",
  "result": [
    {"chunk": 1, "text": "Hello"},
    {"chunk": 2, "text": "world"}
  ]
}
```

Sidecar creates separate messages for each result and routes them independently.

## Error Handling

Errors are routed to `error-end` queue:

| Error Type | Action |
|------------|--------|
| Parse error | Send to error-end with original message |
| Runtime error | Send to error-end with error details |
| Timeout | Send to error-end with timeout message |
| Transport error | NACK for retry |

## Configuration Model

All sidecar configuration via environment variables:
- Container-friendly (no config files)
- Easy per-environment customization
- Validated on startup

Runtime configuration via:
- Environment variables
- ConfigMap (for runtime script injection)
- Secrets (for sensitive data)

## Next Steps

- [Quick Start](quickstart.md) - Deploy your first actor
- [Architecture Overview](../architecture/overview.md) - Detailed architecture
- [Component Documentation](../components/operator.md) - Deep dive into components
