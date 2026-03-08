# Agentic Patterns Tutorial

This tutorial covers the three runtime agentic patterns in Asya that go beyond
static flow compilation — patterns where the actor itself decides routing,
streams output, or suspends for human input at execution time.

---

## Two levels of agentic patterns

Asya supports agentic patterns at two levels:

**Compile-time patterns** (Flow DSL → `asya flow compile`)

Write a Python flow definition; the compiler generates router actors. Routing
conditions are fixed at compile time. Covers sequential pipelines, conditional
dispatch, loops, parallel fan-out, try/except, and more.

See `examples/flows/agentic/` for 15 patterns (ReAct loops, map-reduce,
evaluator-optimizer, human-in-the-loop via approval gate, etc.).

**Runtime patterns** (ABI generator handlers)

Write a generator function that `yield`s ABI instructions during execution.
The actor decides routing, streaming, or suspension based on live data — the
LLM response, the payload content, a risk assessment made at runtime.

This tutorial covers the three runtime patterns:

| # | Pattern | When to use | ABI verb |
|---|---------|-------------|----------|
| 1 | [Dynamic routing](#1-dynamic-routing) | LLM picks the next actor | `SET .route.next` |
| 2 | [Live streaming](#2-live-streaming) | Token-by-token LLM output to UI | `FLY` |
| 3 | [Pause for human input](#3-pause-for-human-input) | Human approval before proceeding | `SET .route.next[:0]` |

---

## 1. Dynamic routing

**ADK equivalent**: `event.actions.transfer_to_agent = "BillingAgent"`

### The problem

Flow DSL compiles static conditionals:

```python
# Flow DSL: conditions fixed at compile time
if state["type"] == "billing":
    state = await billing_agent(state)
elif state["type"] == "tech":
    state = await tech_support(state)
```

This works when you know all possible branches ahead of time. But when an LLM
decides where to route — based on the user's phrasing, conversation history, or
tool outputs — you need runtime routing: the target actor name is determined by
the LLM at execution time.

### How it works

A generator actor reads the LLM's routing decision from the payload and writes
it to `route.next` via the ABI `SET` verb:

```
User query
    |
    v
llm-router actor
    |-- calls LLM, decides target = "billing"
    |-- yield "SET", ".route.next", ["billing-agent"]
    |-- yield payload
    |
    v
billing-agent actor (selected at runtime)
```

### Variant A: Dedicated dispatcher actor

The LLM actor is a plain function that writes `_transfer_to` into the payload.
A downstream dispatcher actor handles routing. This keeps the LLM actor simple
(no ABI needed) and makes the routing logic testable in isolation.

```python
# llm_actor.py — plain function, no ABI
async def llm_actor(payload: dict) -> dict:
    target, response = await call_llm(payload["query"])
    payload["response"] = response
    payload["_transfer_to"] = target  # "billing", "tech", etc.
    return payload
```

```python
# dispatcher.py — generator actor, ABI
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

    # Enum validation: reject hallucinated actor names
    if VALID_TARGETS and target_key not in VALID_TARGETS:
        raise ValueError(f"Unknown target: {target_key!r}. Valid: {sorted(VALID_TARGETS)}")

    actor_name = VALID_TARGETS.get(target_key, target_key)
    yield "SET", ".route.next", [actor_name]
    yield payload
```

Route configuration:

```
llm-actor → dispatcher → (billing-agent | tech-support | general-agent)
                              ↑ decided at runtime by LLM
```

### Variant B: Self-routing LLM actor

Combine the LLM call and routing decision in one actor. One fewer queue hop.

```python
async def llm_router(payload: dict):
    target_key, response = await call_llm_with_routing(payload["query"])
    payload["response"] = response

    if target_key:
        actor_name = VALID_TARGETS.get(target_key, target_key)
        yield "SET", ".route.next", [actor_name]

    yield payload
```

### Enum validation (preventing hallucinated routes)

The LLM may output actor names that don't exist. The enum check catches this
before the routing takes effect:

```python
VALID_TARGETS = {
    key.removeprefix("ASYA_HANDLER_").lower(): queue
    for key, queue in os.environ.items()
    if key.startswith("ASYA_HANDLER_")
}
# e.g. ASYA_HANDLER_BILLING=asya-prod-billing-agent
#      -> VALID_TARGETS["billing"] = "asya-prod-billing-agent"
```

If `_transfer_to` is not in `VALID_TARGETS`, the actor raises `ValueError` and
the envelope is routed to `x-sump` (standard error path). The LLM cannot route
to an actor that isn't in the deployment's allowlist.

### Full example

See `examples/actors/agentic/dynamic_routing.py` for both variants with mock
LLM implementations and real API call comments.

### Testing

```python
import asyncio
from examples.actors.agentic import dynamic_routing

async def test_dispatcher_routing():
    payload = {"_transfer_to": "billing", "query": "invoice help"}
    events = [e async for e in dynamic_routing.dispatcher(payload)]

    # Verify routing was set
    assert ("SET", ".route.next", ["asya-prod-billing-agent"]) in events

    # Verify _transfer_to was cleaned up
    frames = [e for e in events if isinstance(e, dict)]
    assert "_transfer_to" not in frames[0]

asyncio.run(test_dispatcher_routing())
```

---

## 2. Live streaming

**ADK equivalent**: `yield Event(partial=True, content=Part(text=token))`

### The problem

LLMs generate text token by token. Without streaming, the user waits for the
entire response before seeing anything. For long responses (reports, code,
analysis), this is a poor experience.

### How it works

A generator actor yields `FLY` events for each token as it arrives from the
LLM API. FLY events bypass message queues — the sidecar forwards them directly
to the gateway via HTTP, which fans them out as SSE to connected clients.

```
LLM API (token stream)
    |
    v
streaming-llm actor
    |-- yield "FLY", {"type": "text_delta", "token": "Hello"}
    |-- yield "FLY", {"type": "text_delta", "token": " world"}
    |-- yield "FLY", {"type": "text_done"}        -- end signal
    |-- yield payload  (full response downstream)
    |
    v              ↑ simultaneously
next-actor         gateway SSE → client
```

The downstream envelope (with the full response in `payload["response"]`) is
still routed to the next actor normally. FLY events are fire-and-forget: they
do not affect routing.

### Implementation

```python
async def streaming_llm(payload: dict):
    query = payload.get("query", "")

    tokens = []
    async for token in call_llm_streaming(query):
        yield "FLY", {"type": "text_delta", "token": token}
        tokens.append(token)

    yield "FLY", {"type": "text_done"}

    payload["response"] = "".join(tokens)
    yield payload
```

### With Anthropic API

```python
import anthropic

client = anthropic.AsyncAnthropic()

async def call_llm_streaming(query: str):
    async with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": query}],
    ) as stream:
        async for token in stream.text_stream:
            yield token
```

### With OpenAI API

```python
import openai

client = openai.AsyncOpenAI()

async def call_llm_streaming(query: str):
    stream = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": query}],
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
```

### FLY event schema

FLY payloads are arbitrary dicts. The recommended schema for text streaming:

| Field | Value | When |
|-------|-------|------|
| `type` | `"text_delta"` | Each token |
| `token` | `"<token text>"` | Each token |
| `type` | `"text_done"` | End of stream |

Additional fields (model name, token counts, finish reason) can be included
for rich client-side rendering.

### Full example

See `examples/actors/agentic/live_streaming.py` for a complete implementation
with mock and real API variants.

### Testing

```python
import asyncio
from examples.actors.agentic import live_streaming

async def test_streaming():
    payload = {"query": "hello"}
    events = [e async for e in live_streaming.streaming_llm(payload)]

    fly_events = [e for e in events if isinstance(e, tuple) and e[0] == "FLY"]
    text_deltas = [e for e in fly_events if e[1].get("type") == "text_delta"]
    assert len(text_deltas) > 0

    text_done = [e for e in fly_events if e[1].get("type") == "text_done"]
    assert len(text_done) == 1

    frames = [e for e in events if isinstance(e, dict)]
    assert "response" in frames[0]
    assert frames[0]["response"] == "".join(
        e[1]["token"] for e in text_deltas
    )

asyncio.run(test_streaming())
```

---

## 3. Pause for human input

**ADK equivalent**: `should_pause_invocation()` / long-running tool pattern

### The problem

Some decisions are too high-stakes for an LLM to make autonomously. The pipeline
must suspend, wait for human review, collect the human's response, and continue
from where it left off. This is different from the Flow DSL `human_in_the_loop`
pattern (which uses a polling loop where the approval gate is just another actor
in a queue) — here the pipeline is truly suspended and resumed across time.

### How it works

Asya's pause/resume is mediated by two crew actors:

```
your-actor → x-pause → [paused] → x-resume → post-approval-actor
                  ↑                    ↑
                  |   gateway          |
                  +-- marks task as ---+-- receives human input
                      input_required       via A2A endpoint
```

**Your actor** (step 1): detects that pause is needed and prepends `x-pause` to
`route.next`. Puts pause metadata in `payload["_pause_metadata"]`.

**x-pause crew actor** (step 2): persists the full envelope to state proxy storage,
prepends `x-resume` to `route.next`, sets the `x-asya-pause` header. The sidecar
detects this header and reports `paused` status to the gateway. The envelope is
NOT routed onward.

**Gateway** (step 3): marks the task as `paused` (A2A: `input_required`), stores
the pause metadata for the client.

**Client** (step 4): sees `input_required` status. Presents `_pause_metadata.prompt`
and `_pause_metadata.fields` to the user. Sends the user's response via the A2A
task endpoint using the same task ID.

**x-resume crew actor** (step 5): retrieves the persisted envelope, merges the
human's input into the payload, and re-enqueues the envelope to the next actor
in the original route.

**Post-approval actor** (step 6): receives the envelope with human input merged
in. Reads `payload["approved"]`, `payload["notes"]`, etc.

### Implementation

```python
async def analyst(payload: dict):
    result = await analyze_risk(payload)
    payload["analysis"] = result

    if result["risk_level"] == "high":
        # Signal pause: x-pause crew actor handles the gateway mechanics
        yield "SET", ".route.next[:0]", ["x-pause"]

        payload["_pause_metadata"] = {
            "prompt": f"High-risk action: {result['action']}. Approve?",
            "fields": [
                {"name": "approved", "type": "boolean", "label": "Approve", "required": True},
                {"name": "notes",    "type": "string",  "label": "Notes",   "required": False},
            ],
        }

    yield payload


async def post_approval(payload: dict):
    """Runs after x-resume merges human input into payload."""
    if not payload.get("approved"):
        payload["status"] = "rejected"
        payload["reason"] = payload.get("notes", "")
        yield payload
        return

    result = await execute(payload)
    payload["execution_result"] = result
    yield payload
```

### Route configuration

Configure the route so `post_approval` is next after `x-resume`:

```
analyst → x-pause → x-resume → post-approval → x-sink
```

Or in AsyncActor YAML:

```yaml
# The flow entry actor (analyst) defines the route
spec:
  actor: analyst
  # route is set in the envelope; configure via gateway flow registry
```

Gateway flow registry entry (`gateway-flows` ConfigMap):

```yaml
tools:
  - name: high_risk_task
    actor: analyst
    route:
      - x-pause
      - x-resume
      - post-approval
```

The `x-pause` crew actor will prepend `x-resume` automatically if it's missing,
but it's cleaner to include both explicitly in the configured route.

### State proxy requirement

`x-pause` requires `ASYA_PERSISTENCE_MOUNT` to be set — the state proxy volume
where it persists the paused envelope. Without it, persistence is skipped and
resume will not work. Configure it in the AsyncActor spec:

```yaml
spec:
  stateProxy:
    - name: pause-storage
      mount:
        path: /mnt/pause
      connector:
        type: s3
        bucket: my-bucket
        prefix: paused/
```

And set:

```yaml
env:
  - name: ASYA_PERSISTENCE_MOUNT
    value: /mnt/pause
```

### Pause metadata schema

`_pause_metadata` is arbitrary JSON stored by the gateway and returned to
the client in the task status. Recommended schema:

```json
{
  "prompt": "Human-readable description of what is needed",
  "fields": [
    {
      "name": "field_name",
      "type": "boolean|string|number",
      "label": "UI label",
      "required": true
    }
  ]
}
```

### Full example

See `examples/actors/agentic/pause_for_human.py` for a complete analyst +
post_approval implementation with mock risk analysis.

Compare with `examples/flows/agentic/human_in_the_loop.py` which shows the
polling-loop variant using Flow DSL.

---

## Quick reference

| Pattern | Actor type | Key ABI instruction | Crew actors |
|---------|-----------|---------------------|-------------|
| Dynamic routing | Generator | `yield "SET", ".route.next", [target]` | None |
| Live streaming | Generator | `yield "FLY", {"type": "text_delta", "token": t}` | None |
| Pause/resume | Generator | `yield "SET", ".route.next[:0]", ["x-pause"]` | x-pause, x-resume |

## Further reading

- [ABI Protocol Reference](../reference/abi-protocol.md) — full verb reference,
  path syntax, access control, testing patterns
- [Flow DSL Reference](../reference/flow-dsl.md) — compile-time flow patterns
- `examples/flows/agentic/` — 15 Flow DSL agentic patterns
- `examples/actors/agentic/` — ABI generator handler examples (this tutorial)
