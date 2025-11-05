# Architecture Overview

## What is Asya?

Asya is an async actor-based framework for deploying AI workloads on Kubernetes. It treats each AI processing step as an independent async actor (called an "asya") that communicates via message queues and scales independently based on workload.

**Core Concept**: Break complex AI pipelines into specialized, stateless, independent, composable actors. Data ingestion, prompt construction, model routing, pre-processing, and inference each run as independent actors that scale from zero to N replicas based on queue depth.

**Architecture**: Microservices pattern with RabbitMQ message queues, KEDA-driven autoscaling, and sidecar injection via Kubernetes operator. Each actor consists of a message-routing sidecar (Go) and user-defined runtime (Python/any language) communicating over Unix sockets.

**Key Benefits**:
- **Cost Efficiency**: Scale-to-zero when idle, pay only for active processing
- **True Composability**: Mix and match actors, reuse across pipelines
- **Maintainability**: Each actor is independently deployable and testable, and routing code is injected seamlessly via asya-runtime
- **Event-Driven**: Responds to actual workload, not fixed capacity

The framework provides infrastructure (operator, sidecar, gateway) while users focus on implementing their AI logic as simple `process(payload)` functions.

## Deployment Configurations

Asya supports flexible deployment configurations based on your requirements:

### 1. Minimal: CRD + Message Queue

**Components**: Asya Operator + RabbitMQ + KEDA

Deploy actors directly via AsyncActor CRDs without gateway. Ideal for:
- **Batch processing** without strict SLAs
- **Background jobs** triggered by external systems
- **Event-driven pipelines** with simple workflows
- **Cost-sensitive workloads** where scale-to-zero matters

Actors consume from queues, process messages, and route results also via queues. No job tracking, no API layer—just pure queue-driven compute.


### 2. Standard: CRD + Gateway + Message Queue

**Components**: Asya Operator + RabbitMQ + KEDA + Gateway (MCP)

Add the Gateway for synchronous API access with job tracking:
- **Tool integration** via Model Context Protocol (MCP)
- **Job status tracking** with Pending/Running/Succeeded/Failed states, job progress reporting
- **Real-time updates** via Server-Sent Events (SSE streaming - part of MCP protocol)
- **State persistence** in PostgreSQL for job history

The Gateway provides a synchronous, stateful interface while actors remain async and stateless. Perfect for integrating AI pipelines with other tools and services.


### 3. Full Stack: Standard + Monitoring

**Components**: Standard + Prometheus + Grafana

Add observability for production deployments:
- **Metrics dashboards** showing queue depths, replica counts, processing times, supporting alerts, etc
- **Autoscaling visualization** to understand KEDA behavior
- **Performance monitoring** for optimization
- **Alerting** on errors and SLA violations

Recommended for production workloads where visibility is critical.


### 4. Multi-Cluster: Queue-Based Infinite Scale

**Architecture**: Multiple Kubernetes clusters connected to shared RabbitMQ

Asya's queue-based autoscaling enables **out-of-the-box multi-cluster** deployments:
- Actors in **different regions** consume from same queues
- **Cross-region workload distribution** without manual orchestration
- **Infinite horizontal scale** by adding clusters
- **Fault tolerance** across availability zones

Since autoscaling decisions are based on queue depth (not cluster state), actors in any cluster can process messages. This enables:
- **Geographic distribution** for latency optimization
- **Cloud bursting** to overflow clusters
- **Cost optimization** by using spot/preemptible instances across regions
- **Seamless scaling** without reconfiguration

Example: Deploy actors in `us-east-1`, `eu-west-1`, and `ap-south-1` clusters, all consuming from a single RabbitMQ/SQS instance. Workload automatically distributes based on available capacity, no central orchestrator is required.


## System Architecture

Asya is composed of four main components that work together to provide an actor-based framework for AI workloads:

```
┌─────────────────────────────────────────────────────────────────┐
│                         Kubernetes Cluster                      │
│                                                                 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    Asya Operator (asya-system)             │ │
│  │  Watches AsyncActor CRDs → Injects Sidecars → Creates Workloads  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                  │
│                              ▼                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                Async Actor (asya) - CRD                    │ │
│  │                                                            │ │
│  │  ┌──────────────┐         ┌────────────────────────┐       │ │
│  │  │   Sidecar    │◄───────►│   Runtime Container    │       │ │
│  │  │  (Go)        │  Unix   │   (Your AI App)        │       │ │
│  │  │              │  Socket └──────────▲─────────────┘       │ │
│  │  └──────▲───────┘           ┌────────┼──────────┐          │ │
│  │         │                   │ConfigMap: asya.py │          │ │
│  │         │                   └───────────────────┘          │ │
│  └─────────┼──────────────────────────────────────────────────┘ │
│            │                                                    │
│  ┌─────────┼───────┐┌───────────────────────────────────────┐   │
│  │ Required│infra  ││ Asya MCP Gateway infrastructure       │   │
│  │  ┌──────┴──────┐││ ┌──────────────┐ ┌──────────────────┐ │   │
│  │  │  RabbitMQ   │││ │ PostgreSQL   │ │  Prometheus +    │ │   │
│  │  │  (Queues)   │││ │ (Jobs DB)    │ │  Grafana         │ │   │
│  │  └─────▲───────┘││ └─────▲────────┘ └──────────────────┘ │   │
│  └────────┼────────┘└───────┼───────────────────────────────┘   │
│           │                 │                                   │
│  ┌────────┼─────────────────┼─────────────────────────────────┐ │
│  │                Asya MCP Gateway (optional)                 │ │
│  │  MCP Protocol → Job Management → Queue → SSE Streaming     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                             ▲                                   │
└─────────────────────────────┼───────────────────────────────────┘
                              │
                              │
                      MCP Client (HTTP)
```



## Components

### 1. Asya Operator

**Location**: `operator/`
**Language**: Go (Kubebuilder-based)

The operator is a Kubernetes controller that:
- Watches `Asya` custom resources
- Automatically injects sidecar containers
- Creates Deployments, StatefulSets, or Jobs
- Configures KEDA ScaledObjects for autoscaling
- Manages RBAC, ServiceAccounts, and Secrets

See [Operator Component](../components/operator.md) for details.

### 2. Asya Sidecar

**Location**: `src/asya-sidecar/`
**Language**: Go 1.23

The sidecar is a message router that:
- Consumes messages from RabbitMQ queues
- Communicates with runtime via Unix socket
- Routes responses to next queue in pipeline
- Handles errors and retries
- Exposes Prometheus metrics

See [Sidecar Component](../components/sidecar.md) and [Sidecar Architecture](sidecar.md) for details.

### 3. Asya Runtime

**Location**: `src/asya-runtime/`
**Language**: Python 3.13+

The runtime is a Unix socket server that:
- Listens for payloads from sidecar
- Loads user-defined process functions
- Executes processing logic
- Returns results or errors
- Handles size limits and validation

See [Runtime Component](../components/runtime.md) for details.

### 4. Asya Gateway

**Location**: `src/asya-gateway/`
**Language**: Go 1.23

The gateway is an optional MCP server that:
- Implements JSON-RPC 2.0 protocol
- Creates and tracks jobs
- Sends messages to actor queues
- Provides SSE streaming for job updates
- Persists job state in PostgreSQL

See [Gateway Component](../components/gateway.md) for details.


## Message Flow

### Standard Actor Pipeline

```
1. Message arrives in queue
   ↓
2. Sidecar receives message
   │
   ├─ Extracts: route + payload
   ↓
3. Sidecar sends payload to runtime via Unix socket
   ↓
4. Runtime processes payload
   │
   ├─ Success: Returns result
   ├─ Error: Returns error
   └─ Fan-out: Returns array of results
   ↓
5. Sidecar routes based on response
   │
   ├─ Single result → Next step in route
   ├─ Array → Each item to next step
   ├─ Empty → happy-end queue
   └─ Error → error-end queue
   ↓
6. Sidecar ACKs original message
```

### With Gateway

```
1. Client sends MCP request to Gateway
   ↓
2. Gateway creates job (Pending)
   ↓
3. Gateway sends message to first queue
   ↓
4. Actor processes (job becomes Running)
   │
   ├─ Actor sends heartbeats
   ↓
5. Actor completes
   ↓
6. Job updated (Succeeded/Failed)
   ↓
7. Client receives result via SSE stream or polling
```

## Message Structure

All messages follow this format:

```json
{
  "route": {
    "steps": ["queue1", "queue2", "queue3"],
    "current": 0
  },
  "payload": <arbitrary JSON>
}
```

- **route.steps**: Pipeline of queue names
- **route.current**: Current step index (auto-incremented)
- **payload**: Application data

See [Message Flow](messages.md) for detailed message routing.

## Scaling Architecture

### KEDA Integration

```
Queue Depth → KEDA Scaler → HPA → Pod Autoscaling
```

1. KEDA monitors queue depth
2. Compares to target (messages per replica)
3. Adjusts HPA desired replicas
4. Kubernetes scales pods up/down
5. Can scale to zero when idle

**Scaling Policies:**
- Scale up: 100% increase or +4 pods every 15s
- Scale down: 50% decrease every 15s
- Cooldown: 60s before scale to zero

### Horizontal Scaling

Each actor pod is independent:
- Stateless processing
- Shared queue consumption
- No coordination required
- Linear scalability

## Storage Architecture

### Queue (RabbitMQ)

- **Topic Exchange**: Routes messages by queue name
- **Durable Queues**: Survive broker restarts
- **Persistent Messages**: Survive broker restarts
- **Prefetch**: Control concurrent messages per consumer

### Database (PostgreSQL)

Used by Gateway for:
- **jobs table**: Job metadata and state
- **job_updates table**: Audit log for SSE streaming
- **Migrations**: Sqitch-based schema evolution

### Object Storage (Optional)

MinIO or S3 for:
- Large payloads
- Model artifacts
- Training data
- Results storage

## Network Architecture

### Pod Communication

- **Sidecar ↔ Runtime**: Unix socket (`/tmp/sockets/app.sock`)
- **Sidecar ↔ Queue**: TCP (RabbitMQ AMQP)
- **Gateway ↔ Queue**: TCP (RabbitMQ AMQP)
- **Gateway ↔ Database**: TCP (PostgreSQL)

### External Access

- **Gateway**: LoadBalancer or Ingress (port 8080)
- **Grafana**: Port-forward or Ingress (port 3000)
- **RabbitMQ Management**: Port-forward (port 15672)

## Security Architecture

### Authentication

- **RabbitMQ**: Username/password via Secrets
- **PostgreSQL**: Username/password via Secrets
- **Gateway**: No auth (add reverse proxy for production)

### Authorization

- **RBAC**: ServiceAccounts with minimal permissions
- **Pod Security**: Non-root users where possible
- **Network Policies**: Optional isolation

### Secrets Management

- Kubernetes Secrets for credentials
- Environment variable injection
- Reference via secretKeyRef

## Deployment Patterns

### Pattern 1: Direct Actor Deployment

```yaml
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  queueName: my-queue
  workload:
    type: Deployment
    template: {...}
```

Use when:
- Processing from existing queue
- No job tracking needed
- Simple pipelines

### Pattern 2: Gateway + Actors

```
Client → Gateway → Queue → Actor → Queue → ... → happy-end
```

Use when:
- Client-facing API needed
- Job tracking required
- SSE streaming desired
- Multi-step pipelines

### Pattern 3: Fan-Out/Fan-In

```
Actor 1 → [Result1, Result2, Result3] → Queue → Actor 2 (processes each)
```

Use when:
- Parallel processing needed
- Data partitioning required
- Map-reduce patterns

## Observability Architecture

### Metrics (Prometheus)

- **Sidecar metrics**: Message counts, durations, errors
- **Gateway metrics**: Job counts, API latency
- **KEDA metrics**: Queue depth, scaling decisions
- **Custom metrics**: AI-specific (tokens, inference time)

### Logs

- **Structured logging**: JSON format
- **Log levels**: Debug, Info, Warn, Error
- **Correlation IDs**: Trace across components

### Dashboards (Grafana)

- Actor performance
- Queue depths
- Scaling behavior
- Error rates

## High Availability

### Component HA

- **Operator**: Single instance (leader election possible)
- **Gateway**: Stateless, can run multiple replicas
- **Actors**: Horizontal scaling via KEDA
- **RabbitMQ**: Can run clustered
- **PostgreSQL**: Can use managed service

### Failure Modes

- **Pod failure**: Kubernetes restarts
- **Node failure**: Pods rescheduled
- **Queue failure**: Messages persist, actors retry
- **Database failure**: Gateway degraded, actors continue

## Next Steps

- [Sidecar Architecture](sidecar.md) - Detailed sidecar design
- [Message Flow](messages.md) - Message routing details
- [Component Documentation](../components/operator.md)
- [Deployment Guide](../guides/deployment.md)
