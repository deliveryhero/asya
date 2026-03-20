<!-- Type: Tutorial -->

# Agentic Patterns in Asya

Hands-on pattern walkthroughs for developers who know an agentic framework
(Google ADK, LangGraph, CrewAI, Mastra) and want to build equivalent systems
on Asya.

For background on Asya's agentic model, core concepts (envelope, actors,
Flow DSL), and the Flow vs Actor comparison table, see
[Agentic Design](../explanation/agentic-design.md).

For quick-reference tables (ADK pattern map, ABI cheatsheet), see
[Agentic Cheatsheet](../reference/agentic-cheatsheet.md).

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

## See also

| Topic | Document |
|-------|---------|
| Agentic design concepts (envelope, actors, Flow vs Actor) | [docs/explanation/agentic-design.md](../explanation/agentic-design.md) |
| ADK pattern map and ABI quick reference | [docs/reference/agentic-cheatsheet.md](../reference/agentic-cheatsheet.md) |
| ABI verb reference, path syntax, testing | `docs/reference/abi-protocol.md` |
| Flow DSL syntax, supported constructs | `docs/reference/flow-dsl.md` |
| Flow DSL examples (15 patterns) | `examples/flows/agentic/` |
| ABI handler examples (3 patterns) | `examples/actors/agentic/` |
| Gateway security model (auth, dual-deployment) | `docs/architecture/gateway-security-model.md` |
| Envelope protocol and routing semantics | `docs/architecture/protocols/actor-actor.md` |
| State proxy and stateful actors | `src/asya-crew/asya_crew/` |
| AsyncActor XRD reference | `deploy/helm-charts/asya-crossplane/` |
