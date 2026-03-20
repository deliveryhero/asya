# Core Concepts

## Actor Mesh

Asya is an **actor mesh** — a network of stateless actors communicating through message queues. Unlike orchestrated systems where a central coordinator controls the flow, Asya uses **choreography**: each message carries its own route, and actors forward results to the next destination without a central brain.

This architecture provides:

- **Independent failure domains** — a crashed actor does not stall other actors; messages accumulate in its queue until replicas recover
- **Independent scaling** — each actor scales based on its own queue depth via KEDA; a slow GPU inference actor runs on 2 pods while a fast preprocessor scales to 20
- **Queue-native resilience** — messages are durably queued (SQS, RabbitMQ); if an actor pod is evicted, the message is redelivered
- **Stateless actors** — actors are pure functions (`dict -> dict`), can scale to zero, and can be replaced without draining

See [motivation.md](motivation.md) for a deeper comparison of choreography vs orchestration.

## Envelope

The envelope is the fundamental primitive in Asya. It is a JSON message that carries both the data and the route through the pipeline — "the message knows the way."

```json
{
  "id": "env-abc123",
  "parent_id": null,
  "route": {
    "prev": ["preprocess"],
    "curr": "infer",
    "next": ["postprocess", "store"]
  },
  "headers": { "trace_id": "t-42", "priority": "high" },
  "status": {
    "phase": "processing",
    "deadline_at": "2025-11-18T12:05:00Z"
  },
  "payload": { "text": "...", "cleaned": true }
}
```

### Route: prev / curr / next

The route is split into three parts, each with a distinct purpose:

- **`route.prev`** (read-only) — actors that have already processed this envelope. Provides traceability, progress calculation (`len(prev) / total`), and debugging (see which actors an envelope passed through before hitting x-sump).
- **`route.curr`** (read-only) — the actor currently processing the envelope. The sidecar validates that the envelope arrived at the correct destination.
- **`route.next`** (writable) — remaining actors in the pipeline. Actors can modify this for dynamic routing via `yield "SET", ".route.next", [...]`.

Making `next` writable while `prev` and `curr` are read-only enforces a forward-only model: actors can change the future, but they cannot rewrite history.

### Route Advancement

The **runtime** (not the sidecar) advances the route after the handler completes:

1. `curr` is appended to `prev`
2. The first element of `next` becomes the new `curr`
3. `next` shrinks by one

This happens inside the runtime so that any routing changes the handler makes via `yield "SET"` are reflected before advancement.

### Immutable IDs

The `id` field is set when the envelope is created and never changes. This enables deduplication, correlation (the gateway tracks progress by envelope ID), and lineage. When fan-out creates multiple envelopes from one, all children carry `parent_id` pointing to the original.

### Opaque Payload

The sidecar never reads, validates, or modifies the `payload` field. Only the actor handler sees it. Actors append to the payload rather than replacing it, building up a processing record as the envelope moves through the pipeline.

### Status and Deadlines

The optional `status` field is stamped by the gateway: `phase` tracks the lifecycle, and `deadline_at` is an absolute timestamp for SLA pre-checks. If the deadline has passed before calling the runtime, the envelope is routed to x-sink with `phase=failed` — no wasted compute.

**See**: [Envelope spec](reference/specs/envelope.md) for the full protocol.

## Actor

An actor is a Kubernetes workload that processes one envelope at a time. You deploy it as an `AsyncActor` CRD:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: infer
spec:
  image: my-model:latest
  handler: model.LLMHandler.process
  scaling:
    minReplicaCount: 0
    maxReplicaCount: 20
    queueLength: 5
```

Asya creates: one message queue + one Kubernetes Deployment (with sidecar injected) + one KEDA ScaledObject. Deleting the `AsyncActor` cascades to all three.

### Two-File Model

The handler (Python, written by the dev team) and the actor spec (YAML, managed by the platform team) are decoupled. Updating the scaling policy doesn't touch handler code, and changing the model doesn't touch infrastructure. Two files, two owners.

## Sidecar and Runtime

Every actor pod has two containers injected by Asya:

**Sidecar** (Go) handles all infrastructure concerns:

- Polls the SQS/RabbitMQ queue for envelopes
- Forwards envelope to the runtime via Unix socket
- Receives the result and routes it to the next queue
- Exposes Prometheus metrics, handles retries and resiliency policies

**Runtime** (Python) handles all user-code concerns:

- Loads your handler class or function once at startup
- Executes it per envelope
- Returns the result to the sidecar

Your handler sees only `payload: dict -> dict`. The envelope structure, queue mechanics, and routing are invisible to it.

**See**: [Sidecar](reference/components/core-sidecar.md), [Runtime](reference/components/core-runtime.md)

## Crew Actors

Crew actors are built-in system actors that handle framework-level concerns:

| Actor | Role |
|---|---|
| `x-sink` | Persists successful results to S3/MinIO; reports success to the gateway |
| `x-sump` | Final terminal in the two-layer termination chain; emits metrics and logs errors |
| `x-pause` | Checkpoints an envelope to S3 and signals `paused` (human-in-the-loop) |
| `x-resume` | Restores a checkpointed envelope and re-injects it into the mesh |

`x-sink` and `x-sump` are automatic — never include them in route configs. An empty `route.next` or a `None` return routes to `x-sink`. A handler error is retried per the actor's resiliency policy; if exhausted, the envelope goes to `x-sink` (phase: failed). `x-sink` then routes through configured hooks to `x-sump`. This means every pipeline terminates through `x-sink`, regardless of success or failure.

**See**: [Crew](reference/components/core-crew.md)

## Flow DSL

The Flow DSL lets you describe multi-actor pipelines in familiar Python control flow and compiles them into a set of router actors:

```python
async def analysis_flow(p: dict) -> dict:
    p = await clean_text(p)
    if p["language"] == "en":
        p = await english_model(p)
    else:
        p = await multilingual_model(p)
    p = await store_result(p)
    return p
```

`asya flow compile analysis_flow.py` generates router actors that implement the branching logic as message-passing chains using **CPS (continuation-passing style)**. Instead of calling the next function, each step sends a message to the next actor's queue.

Flows support fan-out/fan-in via list comprehensions, list literals, and `asyncio.gather`. Dynamic routing (`yield "SET"`), fire-and-forget fan-out (multiple `yield` without aggregation), and `None` returns are actor-only features.

**See**: [Flow DSL](reference/specs/flow-dsl.md), [Flow Compiler](reference/components/lab-flow-compiler.md)

## Gateway (Optional)

The gateway bridges the synchronous HTTP world with the asynchronous actor mesh. It exposes actor pipelines as MCP tools, A2A agents, or plain HTTP endpoints:

1. Client POSTs to `/mcp` or `/a2a/`
2. Gateway creates a task, sends the envelope to the first actor's queue
3. Sidecars and crew actors report progress back via `/mesh/` callbacks
4. Gateway streams updates to the client via SSE

The gateway runs in two deployment modes: **api** (external-facing A2A/MCP) and **mesh** (internal sidecar callbacks). Both share the same PostgreSQL database for task state.

**See**: [Gateway](reference/components/core-gateway.md)
