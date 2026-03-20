<!-- Type: Usage Guide -->

# Agentic Patterns in Asya

Hands-on pattern walkthroughs for developers who know an agentic framework
(Google ADK, LangGraph, CrewAI, Mastra) and want to build equivalent systems
on Asya.

---

## Overview

Most agentic frameworks provide ready-made agent types: `SequentialAgent`,
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

### Why this model

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

- `payload` — the application data. Actors read and write it. This is your
  conversation state.
- `route.next` — the ordered list of actors still to process this envelope.
  Each actor pops itself off the front and forwards to the next queue.
- `headers` — routing metadata (trace IDs, priority, fan-in signals). Not
  application data.
- `route.prev` / `route.curr` — read-only history of where the envelope has
  been.

### Flow vs Actor capabilities

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

**Why Flow cannot stream tokens (FLY)**: FLY is an ABI instruction that sends
a dict *upstream* to the gateway via a direct HTTP call from the sidecar,
bypassing message queues entirely. Flow router actors are **generated code** —
they only emit ABI instructions for routing (`SET`, `GET`). They never call an
LLM and have nothing to stream. Streaming happens in handler actors.

---

## Patterns

### Fan-out / Fan-in

**ADK equivalent**: `ParallelAgent` / `asyncio.gather` in tools

**When to use**: Multiple independent actors process the same (or different
slices of) the payload in parallel. An aggregator merges the results. This
reduces end-to-end latency when the actors do not depend on each other.

#### Writing the flow

Use `asyncio.gather` in the Flow DSL:

```python
import asyncio

async def analysis_pipeline(state: dict) -> dict:
    state = await preprocessor(state)

    # Fan-out: three independent analyses run in parallel
    state["results"] = list(await asyncio.gather(
        sentiment_analyzer(state["text"]),
        topic_extractor(state["text"]),
        entity_recognizer(state["text"]),
    ))

    # Fan-in: aggregator receives all three results
    state = await aggregator(state)
    return state
```

The compiler generates a fan-out router actor and wires each branch to the
aggregator.

#### What happens internally

The compiled fan-out router emits **N+1 envelopes** from a single incoming
envelope:

```
                          ┌→ sentiment-analyzer ─┐
                          │                       │
incoming envelope → fanout-router → topic-extractor ────→ x-aggregator → aggregator-actor
                          │                       │
                          └→ entity-recognizer ───┘
                          │                       │
                          └→ [parent payload] ─────┘ (slice_index=0)
```

Each emitted envelope carries an `x-asya-fan-in` header that tells the
aggregator what to expect:

```json
{
  "actor": "x-aggregator",
  "origin_id": "env-abc123",
  "slice_count": 4,
  "aggregation_key": "/results",
  "slice_index": 1
}
```

The **x-aggregator crew actor** collects results using the S3 split-key
pattern: each slice writes its result to `s3://bucket/aggregation/{origin_id}/{slice_index}.json`.
Completeness is detected by listing the prefix. When all N+1 slices have
arrived, the aggregator emits a single envelope with all results merged into
`payload["results"]` and routes it to the user-defined aggregator actor.

The split-key pattern means **zero contention**: N actors write to N different
S3 keys simultaneously with no locks, CAS, or coordination. Completeness
detection is an S3 listing. Exactly-once fan-in emission uses atomic
create-if-not-exists on the final merged output key.

#### Map-reduce variant

For processing N items (not N fixed actors), use list comprehension:

```python
async def map_reduce(state: dict) -> dict:
    state = await splitter(state)

    # Fan-out: one actor per item
    state["mapped"] = [await process(item) for item in state["items"]]

    state = await reducer(state)
    return state
```

See `examples/flows/agentic/map_reduce.py` for a full example.

---

### Dynamic routing

**ADK equivalent**: `event.actions.transfer_to_agent = "BillingAgent"`

**When to use**: The next actor is decided by the LLM at runtime, not by a
condition you can enumerate at compile time.

Flow DSL compiles static conditions (`if state["type"] == "billing"`). When
the LLM's output determines the target, use a generator actor with the ABI
`SET` verb:

```python
import os

VALID_TARGETS = {
    key.removeprefix("ASYA_HANDLER_").lower(): queue
    for key, queue in os.environ.items()
    if key.startswith("ASYA_HANDLER_")
}

async def dispatcher(payload: dict):
    target_key = payload.pop("_transfer_to", None)

    if not target_key:
        yield payload
        return

    if VALID_TARGETS and target_key not in VALID_TARGETS:
        raise ValueError(f"Unknown target: {target_key!r}. Valid: {sorted(VALID_TARGETS)}")

    yield "SET", ".route.next", [VALID_TARGETS.get(target_key, target_key)]
    yield payload
```

The **enum validation** (`VALID_TARGETS`) prevents the LLM from hallucinating
an actor name that doesn't exist. The LLM outputs a logical name (`"billing"`);
the dispatcher resolves it to the actual queue name via `ASYA_HANDLER_BILLING`
env var.

**Variant: self-routing LLM actor** — combine the LLM call and routing in one
actor to skip the dispatcher hop.

Full example: `examples/actors/agentic/dynamic_routing.py`

---

### Live streaming

**ADK equivalent**: `yield Event(partial=True, content=Part(text=token))`

**When to use**: LLM generates tokens; the user should see them in real-time
rather than waiting for the full response.

```python
async def streaming_llm(payload: dict):
    tokens = []
    async for token in call_llm_stream(payload["query"]):
        # partial=True: streaming chunk, not persisted, forwarded to UI.
        # ADK equivalent: yield Event(partial=True, content=Part(text=token))
        yield "FLY", {"partial": True, "text": token}
        tokens.append(token)

    # No explicit "done" FLY needed. The downstream yield below is the final
    # (non-partial) frame — equivalent to ADK's Event(partial=False, ...).
    payload["response"] = "".join(tokens)
    yield payload  # downstream to next actor
```

FLY events travel directly from sidecar → mesh gateway → client SSE. They do
not enter the queue. The `partial: True` flag follows ADK's convention:

| ADK | Asya |
|-----|------|
| `Event(partial=True, content=Part(text=token))` | `yield "FLY", {"partial": True, "text": token}` |
| `Event(partial=False, content=...)` — final response | `yield payload` — downstream frame |

The downstream `yield payload` is the final non-partial event. Clients that
mirror ADK's `event.partial` check can filter on `"partial" in event and event["partial"]`.

Full example with Anthropic and OpenAI API snippets:
`examples/actors/agentic/live_streaming.py`

---

### Pause for human input

**ADK equivalent**: `should_pause_invocation()` / long-running tool pattern

**When to use**: The pipeline must suspend, wait for a human decision, then
resume from where it left off.

```python
async def analyst(payload: dict):
    result = await analyze_risk(payload)
    payload["analysis"] = result

    if result["risk_level"] == "high":
        yield "SET", ".route.next[:0]", ["x-pause"]  # signal pause
        payload["_pause_metadata"] = {
            "prompt": f"Approve: {result['action']}?",
            "fields": [
                {"name": "approved", "type": "boolean", "label": "Approve"},
                {"name": "notes",    "type": "string",  "label": "Notes"},
            ],
        }

    yield payload
```

The `x-pause` crew actor persists the envelope, sets the `x-asya-pause` header.
The sidecar detects it and reports `paused` to the gateway. The gateway marks
the task `input_required` (A2A terminology) and notifies the client. When the
client sends a resume message (same task ID via A2A), the gateway routes it to
`x-resume`, which merges human input and re-enqueues the envelope.

```
actor → x-pause ── [task paused, human reviews] ──→ x-resume → post-approval-actor
              ↑                                         ↑
              sidecar sets x-asya-pause           gateway routes resume
```

Compare with `examples/flows/agentic/human_in_the_loop.py`, which shows the
**poll-based approval loop** in Flow DSL: the flow keeps running, hitting an
`approval_gate` actor that polls for human input. The pause/resume pattern
here is a true suspension — the envelope is stored, nothing runs until the
human responds.

Full example: `examples/actors/agentic/pause_for_human.py`

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

---

## Gateway integration

Actors communicate asynchronously through queues. This is efficient and
resilient, but AI clients (LLMs, orchestrators, browsers) speak synchronous
HTTP — they send a request and block waiting for a response.

The **asya-gateway** bridges this gap. It:

1. Receives a synchronous HTTP request (A2A or MCP)
2. Creates a task record and assigns it an ID
3. Sends the initial envelope to the actor queue
4. Streams progress events back to the client as SSE while actors process
5. Returns the final result when the pipeline completes

### A2A protocol

A2A (Agent-to-Agent) exposes actor pipelines as **skills** via a JSON-RPC
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

### MCP protocol

MCP (Model Context Protocol) exposes actor pipelines as **tools** that an LLM
can call via JSON-RPC 2.0.

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

## Quick Reference: ADK → Asya pattern map

| ADK pattern | Asya equivalent | Where |
|------------|----------------|-------|
| `SequentialAgent([A, B, C])` | Linear flow: `state = await A(state); state = await B(state)` | Flow DSL |
| `ParallelAgent([A, B, C])` | `asyncio.gather(A(x), B(x), C(x))` | Flow DSL |
| `LoopAgent(sub_agents, max=5)` | `while` loop in flow DSL | Flow DSL |
| `transfer_to_agent("X")` | `yield "SET", ".route.next", ["x"]` in generator actor | Actor (ABI) |
| `Event(partial=True, content=Part(text=t))` | `yield "FLY", {"partial": True, "text": t}` | Actor (ABI) |
| `should_pause_invocation()` | route to `x-pause`, set `_pause_metadata` | Actor (ABI) |
| `State` (delta-tracked) | `payload` dict (full state, JSON-serialized per hop) | Envelope |
| `output_key` enrichment | `payload["key"] = result` | Anywhere |
| `AgentTool` (agent-as-tool) | standard actor call (same dict→dict interface) | Flow DSL |
| `before/after_model_callback` | no direct equivalent (pre/post actor in pipeline) | Flow DSL |
| Session/conversation history | payload dict or state proxy | Payload / State proxy |

## Quick Reference: ABI yield protocol

```python
# Read metadata
value = yield "GET", ".route.prev"         # who processed this before
value = yield "GET", ".headers.trace_id"   # any header

# Rewrite routing
yield "SET", ".route.next", ["actor_a"]           # replace next
yield "SET", ".route.next[:0]", ["actor_a"]       # prepend to next
yield "SET", ".route.next[999:]", ["actor_a"]     # append to next

# Delete metadata
yield "DEL", ".headers.trace_id"

# Stream upstream to client (SSE)
yield "FLY", {"type": "text_delta", "token": "..."}
yield "FLY", {"type": "text_done"}

# Emit downstream payload (to next actor)
yield payload
```

---

## See also

| Topic | Document |
|-------|---------|
| ABI verb reference, path syntax, testing | `docs/reference/abi-protocol.md` |
| Flow DSL syntax, supported constructs | `docs/reference/flow-dsl.md` |
| Flow DSL examples (15 patterns) | `examples/flows/agentic/` |
| ABI handler examples (3 patterns) | `examples/actors/agentic/` |
| Gateway security model (auth, dual-deployment) | `docs/architecture/gateway-security-model.md` |
| Envelope protocol and routing semantics | `docs/architecture/protocols/actor-actor.md` |
| State proxy and stateful actors | `src/asya-crew/asya_crew/` |
| AsyncActor XRD reference | `deploy/helm-charts/asya-crossplane/` |
