# Architecture

Asya is a Kubernetes-native async actor mesh. All components are designed around one
principle: **the message knows the way**.

## Actor Mesh

<a href="/docs/website/img/actor-mesh.png" target="_blank" title="Click to view full size">
<img src="/docs/website/img/actor-mesh.png" width="100%" style="cursor: zoom-in;" alt="Actor Mesh: gateway, queues, actors with independent KEDA scaling, sink/DLQ"/>
</a>

*Actors communicate through queues. Each message carries its own route. Each actor scales independently via KEDA.*

## Actor Pod Anatomy

<a href="/docs/website/img/actor-anatomy.png" target="_blank" title="Click to view full size">
<img src="/docs/website/img/actor-anatomy.png" width="100%" style="cursor: zoom-in;" alt="Actor pod internals: sidecar, runtime, state proxy, gateway interaction"/>
</a>

*Every actor pod has a sidecar (Go) for queue polling and routing, a runtime (Python) for your handler, and an optional state proxy for virtual persistent memory.*

## Core Components

### Actor Pod (your workload)

Each actor pod has two injected containers:

- **[Sidecar](reference/components/core-sidecar.md)** (Go) — queue polling, envelope routing, retries, progress reporting, metrics
- **[Runtime](reference/components/core-runtime.md)** (Python) — loads your handler, executes per envelope, communicates via Unix socket

Your handler sees only `dict -> dict`. The envelope structure, queue mechanics, and
routing are invisible to it.

### Gateway (optional)

The [gateway](reference/components/core-gateway.md) bridges synchronous HTTP with the async mesh:

| Mode | Audience | Endpoints |
|------|----------|-----------|
| **api** | External clients | `/a2a/` (agents), `/mcp` (tools), `/.well-known/agent.json` |
| **mesh** | Sidecars (internal) | `/mesh` (progress, FLY events, final results) |

Both modes share PostgreSQL for task state. The gateway translates between HTTP
request/response and the fire-and-forget queue-based mesh.

### Crossplane Compositions

[Crossplane](reference/components/core-crossplane.md) manages the declarative lifecycle of actors. Each `AsyncActor` CRD creates:

1. **Message queue** (SQS, RabbitMQ, or Pub/Sub)
2. **Deployment** with sidecar + runtime containers rendered inline
3. **KEDA ScaledObject** watching queue depth

Deleting an `AsyncActor` cascades to all three. No orphaned queues.

### Crew (system actors)

[Crew actors](reference/components/core-crew.md) handle framework-level concerns:

| Actor | Role |
|-------|------|
| `x-sink` | Persists successful results, reports completion to gateway |
| `x-sump` | Terminal error collection, metrics, DLQ |
| `x-pause` | Checkpoints envelope to S3 for human-in-the-loop |
| `x-resume` | Restores checkpointed envelope, re-injects into mesh |

### State Proxy (optional)

The [state proxy](reference/components/core-state-proxy.md) gives actors virtual persistent
memory. Actors read/write `/state/...` paths using standard file I/O — the proxy
translates to S3, GCS, Redis, or NATS KV.

### Flow Compiler (build-time tool)

The [flow compiler](reference/components/lab-flow-compiler.md) transforms Python control
flow (`if/else`, `while`, `asyncio.gather`) into flat actor execution graphs. Purely
additive — generates standard `AsyncActor` manifests.

## Message Flow

1. **Client** sends HTTP request to Gateway (or enqueues directly)
2. **Gateway** creates task, injects envelope into first actor's queue
3. **Sidecar** consumes envelope from queue
4. **Sidecar** forwards payload to Runtime via Unix socket
5. **Runtime** executes your handler, returns result
6. **Sidecar** advances the route, sends envelope to next actor's queue
7. Repeat 3-6 for each actor in `route.next`
8. **x-sink** persists final result, reports status to gateway
9. **Gateway** delivers result to client (blocking wait or SSE stream)

**The core loop**: `Queue -> Sidecar -> Your Code -> Sidecar -> Next Queue`

## Deployment Patterns

### AWS (SQS + S3)

- Crossplane creates SQS queues via AWS Provider
- IAM via IRSA or Pod Identity for queue/S3 access
- Results stored in S3
- KEDA scales via SQS queue depth metrics
- See: [AWS EKS Guide](setup/start-aws-eks.md)

### GCP (Pub/Sub + GCS)

- Crossplane creates Pub/Sub subscriptions via GCP Provider
- IAM via Workload Identity for Pub/Sub/GCS access
- Results stored in GCS
- KEDA scales via Pub/Sub subscription metrics
- See: [GCP GKE Guide](setup/start-gcp-gke.md)

### Local / Self-hosted (RabbitMQ + MinIO)

- RabbitMQ or LocalStack SQS for transport
- MinIO (S3-compatible) for storage
- Username/password auth from K8s secrets
- See: [Quickstart](setup/start-quickstart.md)

## Protocols

- **[Envelope](reference/specs/envelope.md)** — message structure, routing (`prev/curr/next`), status
- **[Sidecar-Runtime](reference/specs/sidecar-runtime.md)** — Unix socket framing, error handling
- **[Gateway API](reference/specs/gateway-api.md)** — A2A, MCP, mesh HTTP endpoints
- **[ABI Protocol](reference/specs/abi-protocol.md)** — generator yield forms (GET, SET, FLY)
- **[AsyncActor CRD](reference/specs/asyncactor-crd.md)** — full manifest reference
- **[Flow DSL](reference/specs/flow-dsl.md)** — flow compilation semantics
