# Core Concepts

## Actors

**What is an Actor?**

An actor is a stateless (by default) workload that:

- Receives messages from an input queue
- Processes them via user-defined code
- Sends results to the next queue in the route

**Key characteristics**:

- Stateless by design - no persistent state between messages
- Independently scalable based on queue depth
- Independently deployable as Kubernetes workloads

**Motivation**: Alternative to monolithic pipelines. Instead of one large pipeline `A → B → C`, each step is an independent actor that can scale and deploy separately.

**See**: [architecture/asya-actor.md](architecture/asya-actor.md) for details.

## Sidecar

**Responsibilities**:

- Message routing between queues and runtime
- Transport management (RabbitMQ, SQS)
- Observability (metrics, logs)
- Reliability (retries, error handling)

**How it works**: Injected as a container into actor pods. Consumes messages from queues, validates message structure, forwards to runtime via Unix socket, routes responses to next queue.

**See**: [architecture/asya-sidecar.md](architecture/asya-sidecar.md) for details.

## Runtime

**Responsibilities**:

- User code execution
- Processing input messages
- Generating output messages

**How it works**: Receives messages from sidecar via Unix socket, loads user handler (function or class), executes it, returns results back to sidecar.

**Deployment**: User defines container image with Python code. Asya injector webhook injects `asya_runtime.py` entrypoint script via ConfigMap.

**See**: [architecture/asya-runtime.md](architecture/asya-runtime.md) for details.

## Crew Actors

**Special system actors** for framework-level tasks:

- **`happy-end`**: Persists successful results to S3/MinIO, reports success to gateway
- **`error-end`**: Handles failures (coming soon), implements retry logic, reports errors to gateway
- more crew actors coming soon

**Future crew actors**:

- Stateful fan-in aggregation
- Custom monitoring and alerting

**See**: [architecture/asya-crew.md](architecture/asya-crew.md) for details.

## Queues

**Interface**: Send, receive, ack, nack messages

**Transport types**:

- **SQS**: AWS-managed queue service
- **RabbitMQ**: Self-hosted open-source message broker

**Pluggable design**: Transport layer is abstracted - adding new transports (Kafka, NATS, Pub/Sub) requires implementing transport interface.

**See**: [architecture/transports/README.md](architecture/transports/README.md) for details.

## Message

**Definition**: JSON object passed between actors via message queues.

**Structure**:
```json
{
  "id": "unique-message-id",
  "route": {
    "actors": ["preprocess", "inference", "postprocess"],
    "current": 0
  },
  "headers": {
    "trace_id": "...",
    "priority": "high"
  },
  "payload": {
    "data": "arbitrary user data"
  }
}
```

**Fields**:

- `id` (required): Unique identifier for tracking
- `route` (required): Actor list and current position
- `payload` (required): User data processed by actors
- `headers` (optional): Routing metadata (traces, priorities)

**Stateful routing**: `route.current` increments after each actor processes the message. Note once again, this is a unique feature of 🎭: pipelines are stateless, but messages are stateful (they represent different pipeline executions).

**See**: [architecture/protocols/actor-actor.md](architecture/protocols/actor-actor.md) for details.

## Crossplane Compositions

**Responsibilities**:

- Manages lifecycle of AsyncActor CRDs
- Creates Kubernetes Deployments/StatefulSets
- Configures KEDA autoscaling
- Creates and manages message queues via cloud providers

**How it works**: Watches AsyncActor custom resources, reconciles desired state via Crossplane Compositions and cloud provider APIs.

**See**: [architecture/asya-crossplane.md](architecture/asya-crossplane.md) for details.

## Injector Webhook

**Responsibilities**:

- Injects asya-sidecar container into actor pods
- Injects asya-runtime entrypoint and ConfigMap
- Configures shared volumes and socket paths

**How it works**: Mutating admission webhook intercepts pod creation, modifies spec to add sidecar and runtime components.

**See**: [architecture/asya-injector.md](architecture/asya-injector.md) for details.

## KEDA (Autoscaling)

**Benefits**:

- Automatic scaling based on queue depth or custom metrics
- Scale to zero - eliminate idle resource costs
- Handle bursty workloads efficiently

**Integration**: Asya Crossplane Composition creates KEDA ScaledObjects for each AsyncActor. KEDA monitors queue depth and scales actor deployments from 0 to maxReplicas.

**Example**: Queue has 100 messages, queueLength=5 configured → KEDA scales to 20 replicas (100/5).

**See**: [architecture/autoscaling.md](architecture/autoscaling.md) for details.

## MCP Gateway (Optional)

As an optional component, 🎭 offers an MCP-compliant HTTP gateway, which allows external clients to easily consume async pipelines as MCP tools.

**Responsibilities**:

- Exposes MCP-compliant HTTP API
- Receives HTTP requests, creates tasks
- Tracks task status in PostgreSQL
- Streams progress updates via Server-Sent Events (SSE)

**How it works**: Client calls tool → Gateway creates task → Sends to first actor's queue → Crew actors report status back → Gateway streams updates to client.

**Use case**: Easy integration for external systems or user-facing APIs.

**See**: [architecture/asya-gateway.md](architecture/asya-gateway.md) for details.

## Observability (Optional)

**Built-in metrics** (OpenTelemetry):

- Actor processing time
- Message throughput
- Error rates
- Queue depth

**Integration**: Prometheus scrapes metrics, Grafana dashboards visualize actor health, pipeline performance.

**See**: [architecture/observability.md](architecture/observability.md) for details.
