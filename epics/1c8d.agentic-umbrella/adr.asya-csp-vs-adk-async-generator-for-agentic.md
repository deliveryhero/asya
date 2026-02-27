# ADR: Asya CPS vs ADK Async Generator -- Agentic Pattern Implementation

> **Status**: Proposed
> **Date**: 2026-02-27
> **Context**: Asya must support all agentic patterns from Google ADK to be fully agentic.
> This ADR documents how Asya's CPS (Continuation-Passing Style) message-passing
> architecture maps to ADK's call-stack-based async generator model, and defines
> the `async for` event accumulation semantics for the Flow DSL.
>
> **Companion**: `survey-adk-data-flow.md` (full ADK pattern survey, 18 patterns mapped)

---

## 1. Decision

Asya adopts a **CPS-based downstream message-passing** model that is architecturally
different from ADK's **call-stack upstream event propagation**, but supports all 17
applicable ADK patterns (18 minus bidirectional streaming which is a different paradigm).

The Flow DSL introduces two actor-call semantics:

| Syntax | Semantics | Wire behavior |
|--------|-----------|---------------|
| `state = await actor(state)` | State transformation. 1-to-1. | 1 message in, 1 message out. |
| `state["events"].extend(event async for event in actor(state))` | Event accumulation. 1-to-N-to-1. | 1 message in, N events fan-in'd, 1 assembled message out. |

The `async for` form uses the existing fan-in infrastructure (epic 1c7i) with
`slice_count` stamped by the sidecar after SSE batching. No new protocols needed.

---

## 2. Context: Two Fundamentally Different Architectures

### ADK: Call-Stack, Events Flow Upstream

ADK uses an in-process generator chain. Events flow **up** the call stack via `yield`:

```
Runner (top)
  ^  yield event
  |  SequentialAgent
  ^    yield event
  |    LlmAgent (ReAct loop)
  ^      yield event
  |      BaseLlmFlow._run_one_step_async()
                produces events
```

Every composition layer (`SequentialAgent`, `LoopAgent`, `ParallelAgent`) uses
`async for event in sub_agent.run_async(ctx): yield event` to forward events to
its parent. The Runner at the top persists events to the session store.

Key properties:
- Events propagate **upstream** through the generator chain
- **Session history** is central (events persisted by Runner)
- **State** is delta-tracked (`event.actions.state_delta`)
- `yield` means "forward this event to my parent"

### Asya: CPS, Messages Flow Downstream

Asya uses distributed actors connected by message queues. Messages flow **downstream**
along `route.next`:

```
router_1 --> actor_a --> router_2 --> actor_b --> x-sink
         msg          msg          msg         msg
```

The flow compiler generates router actors that manipulate `route.next` via VFS
(`/proc/asya/msg/route/next`). There is no call stack. There is no "parent" to
yield to. Each actor processes a message and sends it forward.

Key properties:
- Messages propagate **downstream** along route chains
- **Payload** carries full state (no central session store)
- **State** is the payload itself (enriched at each hop)
- Loops are router self-references in `route.next` (back-edge routers)

### The Critical Insight

ADK's `async for event in sub.run(): yield event` exists because of the call-stack
model -- events must be explicitly forwarded through each generator level to reach
the Runner. Without `yield event`, the parent swallows the event.

Asya doesn't have this problem. Messages flow along `route.next` automatically.
There is no call stack, no generator chain, no need to "forward" events.
**`yield event` in a flow definition is semantically meaningless in CPS** -- there
is no upstream to yield to.

---

## 3. The `async for` Semantics in Asya

### What `async for event in actor(state)` Means

In Asya CPS, `async for event in actor(state)` means:

> "Call this actor (which is a generator handler). Collect all its non-partial
> downstream events. Assemble them into the payload. Continue the flow with
> the assembled state."

This is **event accumulation**, not event propagation. The events don't flow
"upstream" -- they are collected into the payload's event history.

### Proposed Flow DSL Syntax

```python
# Simple accumulation (collect all events into list)
state["events"].extend(event async for event in llm_call(state))

# Accumulation with transform
state["events"].extend(
    {**event, "source": "llm"} async for event in llm_call(state)
)

# Full async-for with body (filter, transform, local vars)
foo_events = []
async for event in llm_call(state):
    if event["is_foo"]:
        foo_events.append(event)
state["events"].extend(foo_events)
```

### Why Not `yield event`?

```python
# REJECTED -- meaningless in CPS
async for event in llm_call(state):
    yield event  # yield to whom? there is no upstream
```

The `yield event` pattern is ADK-specific (upstream propagation). In Asya,
the equivalent operation is explicit accumulation into a payload field.

---

## 4. Implementation: Fan-In via Existing Infrastructure

### How `parseSSEStream` Enables This

The sidecar's `parseSSEStream()` (client.go:150-195) already batches all
downstream events from a generator handler:

```go
case "downstream":
    responses = append(responses, frame)   // collected
case "upstream":
    onUpstream(json.RawMessage(data))      // forwarded immediately to gateway
case "done":
    return responses, nil                  // returns ALL downstream frames
```

After `parseSSEStream` returns, the sidecar knows `N = len(responses)`.

### Fan-In Stamping

When the incoming message has an `x-asya-accumulate` header (set by the
compiler-generated setup router), the sidecar stamps fan-in headers and routes
to the aggregator:

```
parseSSEStream returns [event_1, event_2]  (N=2)

Sidecar routes 3 messages to aggregator queue:
  index 0: parent payload      x-asya-fan-in: {slice_count: 3, slice_index: 0}
  index 1: event_1 payload     x-asya-fan-in: {slice_count: 3, slice_index: 1}
  index 2: event_2 payload     x-asya-fan-in: {slice_count: 3, slice_index: 2}
```

The parent payload (index 0) carries the original state and continuation route.
Event payloads (indices 1..N) carry the actor's downstream outputs.

### Aggregator Behavior

The existing fan-in aggregator (epic 1c7i) handles this with no changes:

1. Receives `slice_count` messages
2. Detects completeness via S3 listing
3. Merges event payloads into `parent_payload["events"]` (or configured `aggregation_key`)
4. Emits 1 assembled message to the continuation router

For N=1 (most common -- LLM yields 1 non-partial event): `slice_count=2`.
Aggregator collects parent + 1 event, merges, emits. Standard fan-in, no
special optimization needed.

### No Done Sentinel Needed

The sidecar knows `N` from the SSE batch. It stamps `slice_count = N + 1`
on each message. The aggregator uses `slice_count` for completeness detection
(existing 1c7i protocol). No sentinel messages, no timeouts.

---

## 5. Compiled CPS for the ReAct Loop

### Flow DSL

```python
async def react_agent(state: dict) -> dict:
    while True:
        state["events"].extend(event async for event in llm_call(state))
        if not state["events"][-1].get("tool_calls"):
            break
        state["events"].extend(event async for event in tool_executor(state))
    return state
```

### Generated Router Network

```
loop_back_router (guarded, max_iterations)
  route.next = [setup_llm, llm_call, aggregator_1, condition_router, self]

setup_llm (generated router)
  stamps x-asya-accumulate header: {target_key: "events", mode: "append"}
  route.next = [llm_call, aggregator_1, condition_router, ...]

llm_call (generator handler)
  yields partial tokens --> upstream (gateway, immediate)
  yields 1+ non-partial events --> downstream (batched by sidecar)
  sidecar: stamps x-asya-fan-in with slice_count, routes to aggregator_1

aggregator_1 (fan-in actor)
  collects all slices, appends events to payload["events"]
  emits 1 assembled message --> condition_router

condition_router (generated)
  if not payload["events"][-1].get("tool_calls"):
    break (exit loop, fall through to continuation)
  else:
    route.next = [setup_tool, tool_executor, aggregator_2, loop_back]

setup_tool (generated router)
  stamps x-asya-accumulate header

tool_executor (handler, may be generator)
  returns tool results
  sidecar: stamps fan-in headers, routes to aggregator_2

aggregator_2 (fan-in actor)
  appends tool results to payload["events"]
  emits 1 message --> loop_back_router

loop_back_router (self-reference)
  re-inserts [setup_llm, llm_call, aggregator_1, condition_router, self]
```

### Payload Evolution

```json
// Start
{"query": "weather in tokyo", "events": []}

// After llm_call (iteration 1)
{"query": "...", "events": [
  {"type": "model_response", "tool_calls": [{"name": "get_weather", "args": {"city": "Tokyo"}}]}
]}

// After tool_executor (iteration 1)
{"query": "...", "events": [
  {"type": "model_response", "tool_calls": [{"name": "get_weather"}]},
  {"type": "tool_response", "name": "get_weather", "result": {"temp": "22C"}}
]}

// After llm_call (iteration 2) -- LLM sees full history, gives final answer
{"query": "...", "events": [
  {"type": "model_response", "tool_calls": [{"name": "get_weather"}]},
  {"type": "tool_response", "name": "get_weather", "result": {"temp": "22C"}},
  {"type": "model_response", "content": "It's 22C and sunny in Tokyo."}
]}
```

This is Asya's equivalent of ADK's session history, built from payload
accumulation via fan-in.

---

## 6. `async for` Body Processing

### Batch Model

The `async for` body runs as a **batch** over collected events, not per-event.
After fan-in assembles all events, a generated body router processes them in
a single invocation:

```python
# User writes:
foo_events = []
async for event in llm_call(state):
    if event["is_foo"]:
        foo_events.append(event)
state["events"].extend(foo_events)

# Compiler generates body router:
def router_body(payload: dict) -> dict:
    p = payload
    events = p.pop("__stream")                    # assembled by fan-in
    foo_events = p.pop("__local__foo_events")     # auto-serialized local var
    for event in events:                           # sync for -- all events here
        if event["is_foo"]:
            foo_events.append(event)
    p["events"].extend(foo_events)
    return payload
```

Local variables (`foo_events`) are handled by the free variable auto-serialization
mechanism (1irj RFC Phase 2): saved to payload before the actor call, restored
in the body router.

### Restrictions

**No `await` in `async for` body.** Actor calls inside the body would require
per-event CPS splits (multi-message continuation within the body). Rejected
for v1. Only mutations, conditionals, and local variable access.

**No `break` in `async for` body.** Events are collected as a batch by fan-in
before the body runs. Breaking mid-stream is impossible because:
1. `parseSSEStream` already collected all events
2. Queue messages may arrive unordered (SQS standard)
3. The body runs over the assembled batch, not a live stream

Use conditional filtering instead:

```python
# Instead of break, filter:
async for event in llm_call(state):
    if event["is_foo"] and not foo_events:  # take only first match
        foo_events.append(event)
```

Compiler error for `break` inside `async for`:

```
FlowCompileError: 'break' is not supported inside 'async for'.
Events are collected as a batch -- use conditional filtering instead.
```

---

## 7. Complete ADK Pattern Mapping

All 18 ADK patterns mapped to Asya CPS:

| # | ADK Pattern | Asya CPS Equivalent | Status |
|---|-------------|---------------------|--------|
| 1 | ReAct while-loop | `while True` + `extend(async for)` + condition router | Ready (needs 1irj for free vars) |
| 2 | Streaming tokens (partial) | `event: upstream` --> gateway (sidecar, transparent) | Done |
| 3 | Parallel tool execution | Fan-out generator + fan-in aggregator (1c7i) | Done |
| 4 | `transfer_to_agent` | VFS `route.next` write or conditional router | Ready (convention) |
| 5 | `output_key` enrichment | Payload mutations (`state["key"] = result`) | Done |
| 6 | SequentialAgent | Route chain `[actor_1, actor_2, ...]` | Done |
| 7 | ParallelAgent | Fan-out + aggregator (1c7i) | Done |
| 8 | LoopAgent + escalate | `while not state["_escalate"]` + payload flag | Ready (convention) |
| 9 | AgentTool (agent-as-tool) | Actor call = isolation boundary (inherent) | Done |
| 10 | Long-running tools | Pause/resume via VFS status (epic 1ixy) | Done |
| 11 | Tool confirmation | Pause/resume variant (`input_required` status) | Ready |
| 12 | Before/after model callbacks | Pre/post actors in route chain | Ready (convention) |
| 13 | Before/after tool callbacks | Pre/post actors in route chain | Ready (convention) |
| 14 | State deltas | Full-state-in-payload (simpler than deltas) | Done |
| 15 | Event compaction | Compactor actor in loop | Ready (convention) |
| 16 | Tool authentication | Pause/resume for credential flow | Ready |
| 17 | Branch isolation | Fan-out = natural isolation (each branch = copy) | Done |
| 18 | Streaming tools (live bidi) | N/A (different paradigm, not queue-based) | N/A |

### Patterns That Need No New Infrastructure

Most ADK patterns map to **conventions** on existing Asya primitives:

- **`_escalate` flag**: Actor sets `state["_escalate"] = True`, while-loop condition
  router checks it. Same as ADK's `tool_context.actions.escalate = True`.
- **`_transfer_to`**: LLM actor sets `state["_transfer_to"] = "billing"`, dispatcher
  router writes to VFS `route.next`. Same as ADK's `transfer_to_agent`.
- **Pre/post callbacks**: Insert actors before/after the target actor in the route
  chain. The "short-circuit" behavior (ADK's callback returning non-None to skip)
  becomes a conditional router checking a flag.
- **Compaction**: Insert a compactor actor before the LLM in the loop. Trims
  `payload["events"]` to manage context window size.

### What Needs Building

| Component | Change | Effort |
|-----------|--------|--------|
| Flow compiler: parser | Detect `extend(async for event in actor(state))` pattern --> `AsyncForAccumulate` IR node | Medium |
| Flow compiler: grouper | Process `AsyncForAccumulate` --> generate setup router + body router | Medium |
| Flow compiler: codegen | Generate setup router (stamps `x-asya-accumulate` header) and body router | Medium |
| Sidecar | When `x-asya-accumulate` header present: stamp `x-asya-fan-in` with `slice_count` on downstream frames | Small |
| Free variable analysis | 1irj Phase 1 (error) and Phase 2 (auto-serialization) -- blocks `async for` body with local vars | Medium (separate epic) |

---

## 8. Integration with Typed Handler Signatures (1ixz)

The `ASYA_PARAMS_AT` and `ASYA_RESULT_AT` mechanisms from the 1ixz RFC provide
the reading counterpart for event accumulation:

```python
# LLM handler reads full state (including events list for context building)
# ASYA_PARAMS_AT=.
async def llm_call(events: list, query: str) -> dict:
    messages = build_openai_messages(events)
    response = await openai.chat.completions.create(messages=messages)
    return {"type": "model_response", "content": response.content,
            "tool_calls": parse_tool_calls(response)}

# Tool handler reads latest event for tool_calls
# ASYA_PARAMS_AT=.events[-1]
async def tool_executor(tool_calls: list) -> dict:
    results = [await execute(tc["name"], tc["args"]) for tc in tool_calls]
    return {"type": "tool_response", "results": results}
```

The handler return value becomes a downstream event. The sidecar stamps fan-in
headers. The aggregator appends it to `payload["events"]`. The next actor reads
from `payload["events"][-1]` or the full list.

---

## 9. Superseded Designs

### 1irj RFC Phase 4 (STALE)

The original Phase 4 proposed `ASYA_PARTIAL_EVENTS_ROUTE` for routing partial events
through queues. This was rejected by the 1ia4 streaming protocol RFC. Phase 4 should
be **closed as unnecessary** -- the `async for` accumulation design in this ADR
replaces it entirely.

### Task 1khyvl (Reject async-for/yield-from)

The task to "reject `async for` / `yield from` across actor boundaries" is partially
correct: `yield from` across actors IS rejected (dual-routing problem). But
`async for` is now supported with accumulation semantics (not upstream propagation).
The task should be updated to reflect:
- Reject: `yield from actor(state)` (no dual-routing)
- Reject: `async for event in actor(state): yield event` (no upstream in CPS)
- Accept: `state["events"].extend(event async for event in actor(state))` (accumulation)
- Accept: `async for event in actor(state): <body without yield/await/break>` (filtered accumulation)

---

## 10. Architectural Insight: Deltas vs Full State

ADK and Asya represent the same computational model with different data flow:

| Aspect | ADK | Asya |
|--------|-----|------|
| Communication | Events flow upstream (generator chain) | Messages flow downstream (route chain) |
| State model | Delta-tracked (`state_delta` on each event) | Full state in payload |
| Session history | Central store (Runner persists events) | Payload field (`state["events"]`) |
| Composition | Generator delegation (`yield from`) | Route manipulation (`route.next`) |
| Isolation | `InMemorySessionService` (AgentTool) | Separate message (natural in CPS) |
| Loops | In-process `while True` | Back-edge router self-reference |
| Parallelism | `asyncio.gather()` | Fan-out + fan-in (1c7i) |
| Streaming | `partial=True` events in generator chain | `event: upstream` SSE (sidecar --> gateway) |

The CPS model is strictly more powerful for distribution: no shared mutable state,
no central session store, no process affinity. Each actor gets the complete payload
and operates independently.

---

## References

- `survey-adk-data-flow.md` -- Full 18-pattern ADK survey with code examples
- `.aint/epics/1irj.flow-free-vars-iteration/rfc.md` -- Free variable analysis RFC (Phase 4 STALE)
- `.aint/epics/.closed/1c7i.stateful-fanin-fanout/rfc.md` -- Fan-in aggregation protocol
- `.aint/epics/1ixz.typed-handler-signatures/rfc.md` -- Typed handler signatures (`ASYA_PARAMS_AT`)
- `.aint/epics/.closed/1fbe.redesign-protocol-sidecar-runtime/epic.md` -- SSE protocol (parseSSEStream)
- `.aint/epics/1ia4.streaming-protocol/task.slopped.1khyvl` -- async-for rejection task (needs update)
