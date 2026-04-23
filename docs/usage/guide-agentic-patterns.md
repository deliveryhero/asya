---
description: "Agentic patterns: fan-out, dynamic routing, conditional branching, LLM streaming, agent swarms"
---

# Agentic Patterns

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

### When to use Flow vs Actor for agentic patterns

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

**Decision guide**:

- **Use a Flow** when the control structure (loops, branches, fan-out) can be
  determined from payload fields at compile time. The ReAct loop, evaluator-
  optimizer, orchestrator-workers, guardrails sandwich, and map-reduce patterns
  all work as flows. The LLM call itself lives in an actor handler; the flow
  provides the outer loop and dispatch logic.

- **Use an Actor** when the behavior requires runtime-only capabilities:
  streaming tokens to the UI (FLY), dynamically choosing the next actor based
  on LLM output (SET .route.next), or suspending for human input (x-pause).
  These are ABI features that only generator handlers can use.

- **Combine both**: most real systems use a Flow for the outer orchestration
  and actors for the inner steps. For example, a ReAct flow compiles to router
  actors, while each tool actor and the LLM actor are standalone handlers that
  may use FLY for streaming.

**Why Flow cannot stream tokens (FLY)**: FLY is an ABI instruction that sends
a dict *upstream* to the gateway via a direct HTTP call from the sidecar,
bypassing message queues entirely. Flow router actors are **generated code** —
they only emit ABI instructions for routing (`SET`, `GET`). They never call an
LLM and have nothing to stream. Streaming happens in handler actors.

---

## Pattern catalog

The [examples/end-to-end/monorepo/agentic](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo/src/agentic/flows) section contains 15+ compilable flow patterns
covering the full spectrum of agentic architectures. The table below maps each
pattern to common framework equivalents and identifies where in this guide it is
explained in detail.

| # | Pattern | Asya primitive | Framework equivalents |
|---|---------|---------------|----------------------|
| 1 | [ReAct tool loop](#react-tool-loop) | Flow: `while True` + `if/elif` dispatch | ADK ReAct, LangGraph prebuilt agent, DSPy ReAct |
| 2 | [Evaluator-optimizer](#evaluator-optimizer) | Flow: `while` + generate + evaluate | Anthropic evaluator-optimizer, ADK LoopAgent |
| 3 | [Orchestrator-workers](#orchestrator-workers) | Flow: `while True` + dynamic dispatch | Anthropic orchestrator-workers, LangGraph supervisor |
| 4 | [Guardrails sandwich](#guardrails-sandwich) | Flow: `try/except` wrapping | OpenAI Agents SDK guardrails, ADK safety plugins |
| 5 | [Fan-out / Fan-in](#fan-out-fan-in) | Flow: `asyncio.gather(...)` | ADK ParallelAgent |
| 6 | [Map-reduce](#fan-out-fan-in) | Flow: list comprehension fan-out | LangGraph map-reduce |
| 7 | [Dynamic routing](#dynamic-routing) | Actor: `yield "SET", ".route.next"` | ADK `transfer_to_agent` |
| 8 | [Live streaming](#live-streaming) | Actor: `yield "FLY", {...}` | ADK `Event(partial=True)` |
| 9 | [Pause for human input](#pause-for-human-input) | Actor: route to `x-pause` | ADK long-running tools, Mastra suspend/resume |
| 10 | Sequential pipeline | Flow: `A -> B -> C -> D` | ADK SequentialAgent |
| 11 | Routing classifier | Flow: `if/elif/else` | ADK conditional routing |
| 12 | Voting ensemble | Flow: fan-out same task N times + judge | Anthropic parallelization (voting) |
| 13 | Hierarchical delegation | Flow: nested `if/elif` + sub-pipelines | ADK tree of agents |
| 14 | Multi-agent debate | Flow: fan-out inside while loop | Academic: Du et al. 2023 |
| 15 | Plan-and-execute | Flow: sequential + `while` step loop | LangGraph plan-and-execute |

Patterns 1-9 are explained in detail below. Patterns 10-15 follow the same
primitives; see [examples/end-to-end/monorepo/agentic](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo/src/agentic/flows) for compilable code.

---

## Patterns

### ReAct tool loop

**Framework equivalents**: ADK `BaseLlmFlow` while-loop, LangGraph prebuilt
ReAct agent, DSPy `dspy.ReAct`, Anthropic agentic loop

**When to use**: An LLM iterates in a Reason-Act-Observe loop: it decides
which tool to call, executes it, observes the result, and loops until it
produces a final answer. This is the foundational pattern for tool-using agents.

```python
async def react_tool_loop(state: dict) -> dict:
    state["iteration"] = 0

    while True:
        state["iteration"] += 1

        # LLM decides: produce tool_calls or final answer
        state = await llm_reason(state)

        # No tool calls = final answer produced
        if not state.get("tool_calls"):
            break

        # Dispatch to the appropriate tool
        tool_name = state["tool_calls"][0]["name"]

        if tool_name == "web_search":
            state = await web_search(state)
        elif tool_name == "code_exec":
            state = await code_exec(state)
        elif tool_name == "calculator":
            state = await calculator(state)

        # Safety: max iterations
        if state["iteration"] >= 10:
            break

    state = await format_response(state)
    return state
```

The flow compiler turns this into router actors. The `while True`, `if/elif`,
and `break` are control flow that compiles to message-passing chains. The actor
calls (`llm_reason`, `web_search`, etc.) become real deployed AsyncActors.

**How it maps**: the `llm_reason` actor calls an LLM API with conversation
history and tool schemas. If the LLM wants a tool, it sets
`state["tool_calls"]`. The compiled condition router dispatches to the right
tool actor. The tool result goes back into state, and the loop iterates.

If the LLM actor also needs to stream tokens, it uses `yield "FLY"` inside its
handler -- the flow provides the outer loop, the actor provides the streaming.
See [Live streaming](#live-streaming) and
[Streaming with FLY Events](guide-streaming.md).

Full example: [`flow_react_tool_loop.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/agentic/flows/flow_react_tool_loop.py)

---

### Evaluator-optimizer

**Framework equivalents**: Anthropic evaluator-optimizer, ADK `LoopAgent` with
exit condition, LangGraph generate/evaluate conditional edge

**When to use**: One actor generates output; a separate actor evaluates it
against quality criteria. If the evaluation fails, feedback loops back to the
generator. The loop continues until quality thresholds are met or max
iterations reached.

```python
SCORE_THRESHOLD = 85
MAX_ITERATIONS = 5

async def evaluator_optimizer(state: dict) -> dict:
    state["iteration"] = 0

    while True:
        state["iteration"] += 1

        # Generate: produce or revise a draft
        state = await generator(state)

        # Evaluate: score the draft and produce feedback
        state = await evaluator(state)

        # Exit: quality threshold met
        if state.get("score", 0) >= SCORE_THRESHOLD:
            break

        # Exit: max iterations
        if state["iteration"] >= MAX_ITERATIONS:
            break

    state = await polisher(state)
    return state
```

The generator and evaluator are separate actors (possibly different LLMs,
different prompts, different scaling). The evaluator writes `state["score"]`
and `state["feedback"]`; the generator reads the feedback on the next
iteration.

Full example: [`flow_evaluator_optimizer.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/agentic/flows/flow_evaluator_optimizer.py)

---

### Orchestrator-workers

**Framework equivalents**: Anthropic orchestrator-workers, LangGraph supervisor
agent, AutoGen `SelectorGroupChat`, ADK `transfer_to_agent` pattern

**When to use**: A central orchestrator LLM decides which worker to invoke at
each step based on accumulated results. Unlike routing classification (static
dispatch), the orchestrator maintains a loop and may invoke different workers
across iterations.

```python
async def orchestrator_workers(state: dict) -> dict:
    state["iteration"] = 0
    state["worker_results"] = []

    while True:
        state["iteration"] += 1

        # Orchestrator decides the next action
        state = await orchestrator(state)

        if state.get("is_complete"):
            break

        # Dispatch to the chosen worker
        if state.get("next_action") == "research":
            state = await data_worker(state)
        elif state.get("next_action") == "analyze":
            state = await analysis_worker(state)
        elif state.get("next_action") == "write":
            state = await writing_worker(state)

        if state["iteration"] >= 10:
            break

    state = await synthesizer(state)
    return state
```

The orchestrator actor is the only one that requires an LLM -- it examines
accumulated worker results and decides `next_action`. The `if/elif` dispatch
compiles to condition routers. Each worker is a separately scaled AsyncActor.

Full example: [`flow_orchestrator_workers.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/agentic/flows/flow_orchestrator_workers.py)

---

### Guardrails sandwich

**Framework equivalents**: OpenAI Agents SDK `input_guardrails` /
`output_guardrails`, ADK safety plugins, ADK before/after model callbacks

**When to use**: Wrap any agent pipeline with input validation (pre-processing)
and output validation (post-processing). If either validation fails, the flow
routes to a safe fallback.

```python
async def guardrails_sandwich(state: dict) -> dict:
    try:
        state = await input_validator(state)
        state = await core_agent(state)
        state = await output_validator(state)
    except Exception:
        state = await safe_fallback(state)
    return state
```

The `try/except` compiles to error routing: if `input_validator`, `core_agent`,
or `output_validator` raises an exception, the envelope is routed to the
`safe_fallback` actor instead of `x-sump`. This gives you the same guardrails
behavior as ADK's `before_model_callback` / `after_model_callback`, but as
explicit actors in the pipeline.

Full example: [`flow_guardrails_sandwich.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/agentic/flows/flow_guardrails_sandwich.py)

---

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
incoming envelope → fanout-router → topic-extractor ────→ fanin-router → aggregator-actor
                          │                       │
                          └→ entity-recognizer ───┘
                          │                       │
                          └→ [parent payload] ─────┘ (slice_index=0)
```

Each emitted envelope carries an `x-asya-fan-in` header that tells the
fan-in aggregator what to expect:

```json
{
  "actor": "fanin-analysis-pipeline-line-8",
  "origin_id": "env-abc123",
  "slice_count": 4,
  "aggregation_key": "/results",
  "slice_index": 1
}
```

The **fan-in aggregator** (a compiler-generated actor backed by
`asya_crew.fanin.split_key.aggregator`) collects results using the S3
split-key pattern: each slice writes its result to its own file under
`/state/checkpoints/fanin/{origin_id}/slice-{index}.json`.
Completeness is detected by listing the directory. When all N+1 slices
have arrived, the aggregator emits a single envelope with all results
merged into `payload["results"]` and routes it to the next actor in the
pipeline.

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

See [`flow_map_reduce.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/agentic/flows/flow_map_reduce.py) for a full example.

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

Compare with [`flow_human_in_the_loop.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/agentic/flows/flow_human_in_the_loop.py), which shows the
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

### Multi-turn conversations

Most agentic frameworks (ADK, LangGraph, Agno) provide built-in session or
memory objects for multi-turn conversations. In Asya, there are two approaches
depending on whether the conversation lives within a single pipeline run or
spans multiple independent invocations.

**Within a single pipeline run**: accumulate conversation history in the
payload. Each actor appends its contribution and the next actor sees the full
history:

```python
async def agent_step(payload: dict) -> dict:
    history = payload.setdefault("conversation", [])

    # Build LLM messages from conversation history
    response = await llm.complete(history + [
        {"role": "user", "content": payload["message"]}
    ])

    history.append({"role": "user", "content": payload["message"]})
    history.append({"role": "assistant", "content": response})

    payload["response"] = response
    return payload
```

For multi-turn with human interaction (chatbot-style), combine this with
pause/resume: the actor routes to `x-pause` after each response, and the
human's next message triggers `x-resume` which loops back to the same actor.
See [Pause/Resume: Human-in-the-Loop](guide-pause-resume.md) for the
multi-turn agentic loop pattern.

**Across separate pipeline invocations**: use the state proxy to persist
conversation history in external storage. Each invocation reads the prior
history, appends to it, and writes it back. See the
[state proxy](#state-proxy-transparent-persistent-storage) section above and
[State Proxy Guide](guide-state-proxy.md) for configuration details.

**A2A task history**: when actors need to report structured progress that
survives pause/resume and is visible to both downstream actors and the
gateway, append to `payload["a2a"]["task"]["history"]`. FLY events are
ephemeral (only for connected SSE clients); history entries are persistent.
See [Streaming with FLY Events](guide-streaming.md) for the distinction.

---

## How Asya compares to other frameworks

All major agentic frameworks (ADK, LangGraph, CrewAI, Mastra, AutoGen, Agno)
run **in-process**: tools, agents, and orchestration share a single Python
runtime. Asya is architecturally distinct -- each actor is a separate container
communicating through message queues.

| Dimension | In-process frameworks | Asya |
|-----------|----------------------|------|
| **Execution model** | Single process, async generators | Distributed pods, message queues |
| **State passing** | Shared memory (delta-tracked dicts) | Full state in payload (JSON per hop) |
| **Scaling** | Scale the whole process | Scale each actor independently |
| **Failure isolation** | One crash kills the pipeline | One crash affects only that actor; messages redelivered |
| **Streaming** | Generator yields or event bus | FLY events (sidecar to gateway, bypasses queues) |
| **Human-in-the-loop** | Callback or suspend/resume in-process | Envelope checkpoint to S3, true suspension |
| **Handler contract** | Framework-specific decorators and types | Plain `dict -> dict` (no imports from Asya) |

The tradeoff: in-process frameworks are simpler to develop and debug locally.
Asya adds operational complexity (Kubernetes, queues, sidecar) but provides
independent scaling, fault isolation, and zero framework lock-in in handler
code.

Asya's handler contract (`dict -> dict`) is intentionally compatible with all
framework tool signatures. A function written as an ADK tool, a LangGraph node,
or a CrewAI tool can be deployed as an Asya actor with a thin adapter -- see
[Actor Handler Patterns](guide-handler-patterns.md) for the adapter pattern.

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

# Invoke a skill via A2A JSON-RPC
curl -X POST https://my-gateway/a2a/ \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","parts":[{"text":"Summarize this: ..."}]},"metadata":{"skill":"my-skill"}}}'
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
| `canceled` | `canceled` | Task canceled by client |
| `auth_required` | `auth_required` | Authentication required before proceeding |

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
    flows:
      - name: document-summarizer
        description: Summarizes documents using LLM
        entrypoint: start-document-pipeline  # first actor in the pipeline
        route_next:
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
| Streaming with FLY events | [guide-streaming.md](guide-streaming.md) |
| Pause/Resume: Human-in-the-Loop | [guide-pause-resume.md](guide-pause-resume.md) |
| Actor handler patterns and adapters | [guide-handler-patterns.md](guide-handler-patterns.md) |
| State proxy and persistent storage | [guide-state-proxy.md](guide-state-proxy.md) |
| ABI verb reference, path syntax, testing | [ABI Protocol](../reference/specs/abi-protocol.md) |
| Flow DSL syntax, supported constructs | [Flow DSL](../reference/specs/flow-dsl.md) |
| Flow DSL examples (19 patterns) | [examples/end-to-end/monorepo/agentic](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo/src/agentic/flows) |
| ABI handler examples (3 patterns) | `examples/actors/agentic/` |
| Gateway security model (auth, dual-deployment) | [Gateway](../reference/components/core-gateway.md) |
| Envelope protocol and routing semantics | [Envelope](../reference/specs/envelope.md) |
| Core concepts (actor mesh, choreography) | [Concepts](../concepts/README.md) |
