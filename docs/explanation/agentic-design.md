<!-- Type: Explanation -->

# Agentic Design in Asya

Background on how Asya's agentic model differs from other frameworks,
core concepts (envelope, actors, Flow DSL), and the Flow vs Actor
capability comparison.

---

## Asya vs other agentic frameworks

Most frameworks provide ready-made agent types: `SequentialAgent`,
`ParallelAgent`, `LoopAgent`, `ReActAgent`. The framework is smart; your code
plugs into it.

**Asya takes the opposite approach: the framework is dumb; your code is
explicit.**

There are no built-in agent types. Instead Asya provides two primitives:

| Primitive | What it is | Analogy |
|-----------|-----------|---------|
| **Actor** | A stateless function that transforms a payload dict | A single tool / function call in ADK |
| **Flow** | A Python file that describes control flow between actors | An agent definition — but compiled, not interpreted |

You express orchestration patterns (sequential, parallel, conditional, loop)
as a **Flow DSL** file, which the compiler turns into router actors deployed on
Kubernetes. Inner business logic — LLM calls, API calls, data transforms —
lives in regular Python actor handlers.

This explicit model has concrete benefits:

- **No hidden state machine**: the routing graph is visible code, not an
  invisible framework loop.
- **Each actor is a separate pod**: actors scale independently, restart
  independently, and are billed independently.
- **No framework lock-in in actor code**: actor handlers are plain Python
  functions with no Asya imports. You can run and test them locally without
  any Asya infrastructure.
- **Choreography over orchestration**: there is no central runner that drives
  the flow. Envelopes carry their own routing table; each actor advances the
  route and passes the envelope to the next queue.

---

## Core concepts

### The envelope

Every message in Asya is an **envelope**:

```json
{
  "id": "env-abc123",
  "route": {
    "prev": ["start-router", "preprocessor"],
    "curr": "llm-actor",
    "next": ["formatter", "notifier"]
  },
  "headers": {"trace_id": "t-xyz", "priority": "high"},
  "payload": {"query": "summarize this document", "text": "..."}
}
```

- `payload` — the application data. Actors read and write it.
- `route.next` — the ordered list of actors still to process this envelope.
  Each actor pops itself off the front and forwards to the next queue.
- `headers` — routing metadata (trace IDs, priority, fan-in signals). Not
  application data.
- `route.prev` / `route.curr` — read-only history of where the envelope has
  been.

**The payload is the conversation state.** Actors pass it forward; downstream
actors see everything upstream actors wrote. There is no separate "state store"
for typical single-conversation pipelines.

### Actors

An actor is a Python function (or class method) that transforms a payload:

```python
# Function actor — simplest form
async def summarizer(payload: dict) -> dict:
    payload["summary"] = await llm.complete(payload["text"])
    return payload
```

Actors know nothing about Asya. They have no imports from the framework; they
work in isolation. Each actor runs in its own Kubernetes pod, consuming from
its own SQS queue (or RabbitMQ exchange).

**Generator actors** have `yield` statements and can communicate with the
platform via the ABI protocol (see [Flow vs Actor](#flow-vs-actor-what-each-can-and-cannot-do) below).

### Flow DSL

A Flow is a Python file that describes how actors are connected:

```python
async def document_pipeline(state: dict) -> dict:
    state = await preprocessor(state)       # sequential

    if state["doc_type"] == "legal":
        state = await legal_analyzer(state) # conditional branch
    else:
        state = await general_analyzer(state)

    state = await formatter(state)
    return state
```

You compile it:

```bash
asya flow compile document_pipeline.py --output-dir compiled/ --plot
```

The compiler generates `compiled/routers.py` — router actors that implement
the control flow using the ABI protocol internally. You deploy these routers
alongside your handler actors. At runtime, routers are pods that receive
envelopes, decide the next actor, and forward.

See `examples/flows/agentic/` for 15 patterns (ReAct loops, evaluator-optimizer,
map-reduce, parallel fan-out, human-in-the-loop, etc.).

### Flow vs Actor: what each can and cannot do

| Capability | Flow DSL | Actor handler |
|-----------|----------|---------------|
| Sequential chain | ✅ `state = await actor_a(state)` | n/a (you are the actor) |
| Conditional routing | ✅ `if/elif/else` | ✅ via ABI `SET .route.next` |
| Loops | ✅ `while` / `for` | n/a |
| Fan-out / Fan-in | ✅ `asyncio.gather(...)` | possible but manual |
| Try/except | ✅ | via error routing |
| **Stream tokens to UI (FLY)** | ❌ not possible | ✅ `yield "FLY", {...}` |
| Dynamic routing at runtime | ❌ compile-time only | ✅ `yield "SET", ".route.next", [...]` |
| Read envelope metadata | ❌ | ✅ `yield "GET", ".route.prev"` |
| Pause for human input | ❌ | ✅ route to `x-pause` crew actor |

**Why Flow cannot stream tokens (FLY)**

FLY is an ABI instruction that sends a dict *upstream* to the gateway via a
direct HTTP call from the sidecar, bypassing message queues entirely:

```python
# Inside a generator actor:
async for token in llm.stream(payload["query"]):
    yield "FLY", {"type": "text_delta", "token": token}
```

The sidecar intercepts each `FLY` yield and forwards the dict to the mesh
gateway over HTTP. The gateway fans it out as an SSE event to any client
subscribed to that task's stream. This is how LLM token streaming reaches the
browser in real-time, without waiting for the full response.

Flow router actors are **generated code** — they only emit ABI instructions for
routing (`SET`, `GET`). They never call an LLM and have nothing to stream.
Streaming happens in handler actors, which hold the LLM connection and yield
`FLY` events.

---

## State management

### Payload as conversation state

The payload dict is the conversation state. Every actor reads from it and
writes to it. Downstream actors see everything upstream actors wrote.

This is the same concept as ADK's `State` object, but simpler: there is no
delta tracking, no scope prefix system, no compaction. What you write is what
the next actor reads.

```python
# Actor A
async def actor_a(payload: dict) -> dict:
    payload["answer"] = await llm.complete(payload["question"])
    return payload

# Actor B sees payload["answer"] written by A
async def actor_b(payload: dict) -> dict:
    payload["formatted"] = f"Answer: {payload['answer']}"
    return payload
```

**Constraint**: payloads must be JSON-serializable (they travel through SQS/
RabbitMQ). For large binary data (model weights, media files), store a reference
(S3 URL, artifact ID) in the payload and keep the actual data in external
storage.

### State proxy: transparent persistent storage

For use cases that need persistent state across messages or across actors —
conversation history, per-user context, fan-in aggregation — Asya provides
the **state proxy**.

The state proxy is a sidecar container injected alongside the actor runtime.
It exposes a local filesystem path (e.g., `/state/`) that maps to a remote
storage backend (S3, GCS, Redis, NATS KV). Actor code uses standard Python
file I/O; the runtime transparently translates it to storage operations:

```python
import json
import os

STATE_PATH = os.environ.get("ASYA_STATE_MOUNT", "/state")

async def context_actor(payload: dict) -> dict:
    user_id = payload["user_id"]
    history_path = f"{STATE_PATH}/history/{user_id}.json"

    # Read prior conversation history (if exists)
    try:
        with open(history_path) as f:
            history = json.load(f)
    except FileNotFoundError:
        history = []

    history.append({"role": "user", "content": payload["message"]})
    response = await llm.complete(history)
    history.append({"role": "assistant", "content": response})

    # Write updated history
    with open(history_path, "w") as f:
        json.dump(history, f)

    payload["response"] = response
    return payload
```

Configure via `spec.stateProxy` in the AsyncActor manifest:

```yaml
spec:
  actor: context-actor
  stateProxy:
    - name: user-history
      mount:
        path: /state
      connector:
        type: s3
        bucket: my-bucket
        prefix: actor-state/
```

For local development without Kubernetes, the mount path is a real directory —
actor code works identically.

The fan-in aggregator (`x-aggregator` crew actor) uses the state proxy
internally for the split-key pattern.

---

## Gateway: connecting agents to the world

### Why a gateway

Actors communicate asynchronously through queues. This is efficient and
resilient, but AI clients (LLMs, orchestrators, browsers) speak synchronous
HTTP — they send a request and block waiting for a response.

The **asya-gateway** bridges this gap. It:

1. Receives a synchronous HTTP request (A2A or MCP)
2. Creates a task record and assigns it an ID
3. Sends the initial envelope to the actor queue
4. Streams progress events back to the client as SSE while actors process
5. Returns the final result when the pipeline completes

```
Client (LLM / browser)
        │ POST /a2a/{skill}
        │
        ▼
  asya-gateway-api          (ClusterIP + Ingress, auth enforced)
        │ enqueue
        ▼
  SQS / RabbitMQ
        │
        ▼
  Actor pipeline ...
        │ FLY events → sidecar → asya-gateway-mesh → SSE → client
        │ final result → x-sink → gateway mesh → task completed
        ▼
  Client receives streamed updates + final result
```

### Dual-deployment architecture

The gateway runs as two deployments from the same binary, selected by the
`ASYA_GATEWAY_MODE` environment variable:

| Deployment | Mode | Routes | External access | Auth |
|-----------|------|--------|----------------|------|
| `asya-gateway-api` | `api` | `/a2a/*`, `/mcp`, `/.well-known/*` | Yes (Ingress) | Protocol-native |
| `asya-gateway-mesh` | `mesh` | `/mesh/*` | No (ClusterIP only) | Network isolation |

Sidecars reach the mesh gateway via in-cluster DNS
(`asya-gateway-mesh.{namespace}.svc.cluster.local`). External clients reach
the API gateway via Ingress. Mesh routes are **unreachable from outside the
cluster by network topology**, not by middleware auth.

### A2A protocol

A2A (Agent-to-Agent) is the gateway's external interface for AI agent
interoperability. It exposes actor pipelines as **skills** via a JSON-RPC
endpoint.

```bash
# Discover available skills
curl https://my-gateway/.well-known/agent.json

# Invoke a skill
curl -X POST https://my-gateway/a2a/my-skill \
  -H "X-API-Key: $API_KEY" \
  -d '{"message": {"parts": [{"text": "Summarize this: ..."}]}}'
```

A2A responses use **task semantics**: the call returns a task ID immediately
(`submitted`), then streams status updates (`working`, `input_required`) and
finally the result (`completed`). This matches the async actor model directly.

Key A2A states and their Asya equivalents:

| A2A state | Asya internal | Meaning |
|-----------|--------------|---------|
| `submitted` | `pending` | Envelope queued, not yet picked up |
| `working` | `running` | Actor(s) processing |
| `input_required` | `paused` | Waiting for human input (x-pause) |
| `completed` | `succeeded` | x-sink received final result |
| `failed` | `failed` | x-sump received error envelope |

Auth: API key (`X-API-Key`) or JWT Bearer token. See
`docs/architecture/gateway-security-model.md` for the full security model.

### MCP protocol

MCP (Model Context Protocol) is the gateway's interface for LLM tool calling.
It exposes actor pipelines as **tools** that an LLM can call via JSON-RPC 2.0.

```bash
# List available tools
curl https://my-gateway/mcp -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# Call a tool (LLM-initiated)
curl https://my-gateway/mcp -d '{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {"name": "my-tool", "arguments": {"text": "..."}},
  "id": 2
}'
```

MCP supports SSE streaming (`/mcp/sse`) for real-time tool output — FLY events
from actors arrive at the client as streaming text chunks.

Auth: API key (Phase 2) or OAuth 2.1 with PKCE (Phase 3, full MCP spec
compliance). See `docs/architecture/gateway-security-model.md`.

### Flow registry: exposing actor pipelines as tools/skills

Which pipelines are exposed via A2A and MCP is configured in the
`gateway-flows` ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gateway-flows
data:
  flows.yaml: |
    tools:
      - name: document-summarizer
        description: Summarizes documents using LLM
        actor: start-document-pipeline  # entry router actor
        route:
          - preprocessor
          - llm-summarizer
          - formatter
```

The gateway polls this ConfigMap at runtime (configurable via
`ASYA_CONFIG_POLL_INTERVAL`). Updating the ConfigMap updates the exposed
tools without restarting the gateway.

---

## See also

- [Agentic Patterns Tutorial](../tutorials/agentic-patterns.md) — hands-on
  pattern walkthroughs (fan-out, dynamic routing, streaming, pause/resume)
- [Agentic Cheatsheet](../reference/agentic-cheatsheet.md) — ADK-to-Asya
  pattern map and ABI quick reference
- [Flow DSL Reference](../reference/flow-dsl.md) — syntax rules and
  compilation details
- [ABI Protocol Reference](../reference/abi-protocol.md) — yield-based
  metadata access
