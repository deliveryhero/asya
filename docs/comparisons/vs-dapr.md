---
description: "Deep comparison: Asya vs Dapr — both inject sidecars, different architecture philosophy"
---

# vs Dapr

## TL;DR

Dapr and Asya both inject a sidecar into your Kubernetes pods -- but for
different reasons. Dapr is a **general-purpose distributed application runtime**
that abstracts cloud services behind stable HTTP/gRPC APIs. Asya is a
**purpose-built actor mesh** where stateless handlers communicate through
durable queues, the message carries its own route, and every actor scales
independently to zero via KEDA. Portable microservice abstraction? Dapr.
Queue-based AI/ML pipelines with per-actor GPU scaling and no SDK? Asya.

## At a Glance

| | 🎭 | Dapr |
|---|---|---|
| **One-liner** | Actor mesh for AI workloads on K8s | Portable distributed application runtime |
| **Execution model** | Choreography: envelope carries the route | Orchestration: app calls Dapr APIs to publish, invoke, manage state |
| **Sidecar role** | Queue I/O, routing, retries, envelope lifecycle | API gateway to pluggable infrastructure (state, pub/sub, bindings, actors) |
| **Handler UX** | Pure `dict -> dict` Python function | Any HTTP/gRPC server; use Dapr SDK for convenience |
| **Actor model** | Stateless by default; optional state proxy sidecar | Virtual actors (turn-based, single-threaded, in-memory state) |
| **Scaling** | Per-actor via KEDA (queue depth) | App-level; KEDA available but not integrated by default |
| **Scale to zero** | 🟢 Native (KEDA scales pods 0-N) | 🔴 Actor placement requires running hosts |
| **State management** | State travels in envelope; optional state proxy (S3, Redis, NATS KV) | Built-in state store API (Redis, CosmosDB, DynamoDB, 20+ backends) |
| **Pub/Sub** | Transport layer: SQS, RabbitMQ, GCP Pub/Sub | Component API: Kafka, RabbitMQ, Redis Streams, 15+ backends |
| **Workflow engine** | Flow DSL compiles Python to actor routes (no runtime engine) | Dapr Workflow: durable execution via replay (similar to Temporal) |
| **K8s native** | 🟢 CRDs, Helm, Crossplane, GitOps | 🟡 Runs on K8s but no CRDs for apps; Dapr components are CRDs |
| **SDK requirement** | ✅ None (plain Python functions) | ⚠️ Optional but recommended (Go, Python, Java, .NET, JS, Rust) |
| **Dynamic routing** | ✅ Actors rewrite `route.next` at runtime | ⚠️ App-level: publish to different topics or invoke different services |
| **Agentic support** | ✅ A2A, MCP, pause/resume, FLY streaming | ⚠️ Not built-in; achievable via workflows + pub/sub |
| **Maturity** | 🟡 Alpha (production at Delivery Hero) | 🟢 Mature (CNCF Graduated, v1.x stable) |

## Architecture Comparison

### Dapr Sidecar Model

Dapr injects a `daprd` sidecar that exposes a **local HTTP/gRPC API** to the
app container. The app calls `localhost:3500` to perform state operations,
publish messages, invoke services, or interact with virtual actors. Dapr
translates these calls to the configured backend using **component definitions**
-- Kubernetes CRDs that describe the backing service.

```
┌──────────────────────────────────┐
│  Pod                             │
│  ┌────────┐    ┌──────────────┐  │
│  │ Your   │───>│  daprd       │──────> Redis / Kafka / ...
│  │ App    │<───│  :3500 HTTP  │  │
│  └────────┘    └──────────────┘  │
└──────────────────────────────────┘
```

The app **drives** the sidecar: it decides when to read state, publish events,
or invoke services.

### Asya Sidecar Model

Asya also injects a sidecar, but the relationship is inverted. The **sidecar
drives the app**: it pulls messages from the queue, delivers the envelope to the
handler over a Unix socket, receives the response, and routes it to the next
queue based on the envelope's `route.next` field.

```
┌──────────────────────────────────┐
│  Pod                             │
│  ┌────────────┐  ┌────────────┐  │
│  │ asya-      │─>│  Runtime   │  │    SQS / RabbitMQ /
│  │ sidecar    │<─│  (Python)  │  │    GCP Pub/Sub
│  └─────┬──────┘  └────────────┘  │
│        └─────────────────────────────> Next actor's queue
└──────────────────────────────────┘
```

The handler never calls the sidecar. It receives a dict, returns a dict, and the
sidecar handles everything else. **Dapr's sidecar is a service API the app
calls. Asya's sidecar is a message pump that calls the app.**

## Developer Experience

Consider building a 3-step pipeline: validate input, call an LLM, store the
result.

### Dapr

```python
# app.py -- HTTP server; each handler publishes to the next topic via Dapr SDK
from dapr.clients import DaprClient
from flask import Flask, request

app = Flask(__name__)

@app.route("/validate", methods=["POST"])
def validate():
    data = request.json
    data["validated"] = True
    with DaprClient() as client:
        client.publish_event("pubsub", "llm-topic", json.dumps(data))
    return "", 200

@app.route("/call-llm", methods=["POST"])
def call_llm():
    data = request.json
    data["response"] = model.generate(data["prompt"])
    with DaprClient() as client:
        client.publish_event("pubsub", "store-topic", json.dumps(data))
    return "", 200
```

Each handler must know the next topic to publish to. Routing is hardcoded in
application code. You also need Dapr component CRDs for the pub/sub and state
store, plus subscription resources wiring topics to endpoints.

### Asya

```python
# handler.py -- plain functions, no SDK, no imports
def validate(state: dict) -> dict:
    return {**state, "validated": True}

def call_llm(state: dict) -> dict:
    state["response"] = model.generate(state["prompt"])
    return state

def store_result(state: dict) -> dict:
    db.save(state)
    return state
```

```yaml
# asyncactor.yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: call-llm
spec:
  image: my-pipeline:latest
  handler: handler.call_llm
  scaling:
    minReplicaCount: 0
    maxReplicaCount: 10
  resiliency:
    actorTimeout: 300s
    policies:
      default:
        maxAttempts: 3
        backoff: exponential
```

Handlers have no knowledge of routing, topics, or infrastructure. The envelope
carries the route. Retry policies and scaling live in the Kubernetes manifest.

## When to Choose Dapr

Dapr is a mature CNCF graduated project with broad adoption. It is the stronger
choice when:

- **Polyglot microservices** -- you run services in Go, Java, .NET, Python, and
  Rust side by side and want a uniform API for state, pub/sub, and service
  invocation across all languages.
- **Service-to-service invocation** -- Dapr provides built-in service discovery,
  mutual TLS, and retries for synchronous request/reply between microservices.
- **State store abstraction** -- your services need key-value state access across
  20+ backends (Redis, CosmosDB, PostgreSQL, DynamoDB) with transactions and
  ETags, and you want to swap backends without code changes.
- **Virtual actor requirements** -- Dapr's actor model provides turn-based
  concurrency, timers, and reminders with automatic placement across hosts.
  Useful for per-entity stateful processing (IoT devices, user sessions, game
  objects).
- **Bindings and triggers** -- Dapr supports input/output bindings to external
  systems (Cron, SMTP, Twilio, S3) with a uniform component model.
- **Non-Kubernetes environments** -- Dapr runs standalone (self-hosted mode)
  on bare metal, VMs, or edge devices. Asya requires Kubernetes.

## When to Choose Asya

Asya is purpose-built for AI/ML workloads on Kubernetes:

- **Per-actor GPU scaling** -- an LLM inference actor on A100 GPUs scales 0-5
  while a preprocessing actor on CPU scales 0-50, each driven by its own queue
  depth. Dapr has no built-in per-handler autoscaling.
- **Scale-to-zero** -- KEDA scales actor pods to zero when queues are empty. GPU
  pods cost nothing between batches. Dapr virtual actors require running host
  processes to maintain placement.
- **No SDK lock-in** -- handlers are plain Python functions (`dict -> dict`).
  No SDK, no decorators, no HTTP server boilerplate. Swap the function,
  redeploy.
- **Routing is data, not code** -- the envelope carries its route. Actors can
  dynamically rewrite `route.next` at runtime (e.g., an LLM judge routes
  high-confidence results to storage and low-confidence to human review). In
  Dapr, routing logic lives in application code.
- **Simpler mental model for pipelines** -- one abstraction (actor) instead of
  components, subscriptions, topics, bindings, and service invocation. Platform
  engineers own the YAML; data scientists own the Python function.
- **K8s-native operations** -- AsyncActor is a CRD. Deploy with `kubectl apply`,
  manage with Helm, compose with Crossplane. Full GitOps compatibility.
- **Agentic AI patterns** -- built-in A2A and MCP gateway, pause/resume for
  human-in-the-loop, FLY streaming for live token output. Dapr has no
  native agent protocol support.
- **Queue-native resilience** -- if an actor pod is evicted mid-processing, the
  message reappears and another replica picks it up. No checkpointing needed.
