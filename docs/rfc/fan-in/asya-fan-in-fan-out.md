# RFC: Stateful Fan-In/Fan-Out for Agentic Workflows

**Status**: Draft
**Author**: Architecture Discussion
**Date**: 2026-01-28
**Updated**: 2026-02-10
**Related**: agentic-compiler-rfc.md, asya-handler-signatures.md

---

## Executive Summary

This RFC defines the design for stateful fan-in/fan-out in Asya, enabling dynamic parallel execution of sub-agents with result aggregation. The design supports **three syntax levels** — sync list comprehensions, async list comprehensions, and `asyncio.gather` — all compiling to the same distributed fan-out/fan-in actor networks on Asya. The difference is only in local execution: list comprehensions run sequentially, `asyncio.gather` runs with true concurrency.

**Key Innovations**:
- **Three syntax levels**: Sync comprehensions, async comprehensions (sequential locally), and `asyncio.gather` (parallel locally) — all compile to distributed fan-out as a compiler optimization
- **Dynamic fan-out**: N determined at runtime from payload values
- **Setup + slice message pattern**: N+1 messages total (1 setup, N slices)
- **Pre-increment + pre-merge**: Aggregator prepares envelope before DB write, CDC emits as-is
- **ADK-compliant streaming**: Async generators with `partial` field classification
- **CPS-compatible**: Integrates with the agentic compiler's Continuation-Passing Style transformation

---

## Table of Contents

1. [Background](#background)
2. [Flow DSL Syntax](#flow-dsl-syntax)
3. [Fan-Out Architecture](#fan-out-architecture)
4. [Fan-In Aggregator Design](#fan-in-aggregator-design)
5. [Async Generator Streaming](#async-generator-streaming)
6. [Sub-Agent Context Isolation](#sub-agent-context-isolation)
7. [Implementation Details](#implementation-details)
8. [Open Questions](#open-questions)
9. [References](#references)

---

## Background

### The Problem

Agentic workflows often require parallel execution of sub-tasks:

```python
# Sync flow (existing compiler)
def analyze_flow(p: dict) -> dict:
    p["results"] = [research_agent(p["tasks"][i]) for i in range(len(p["tasks"]))]
    return p

# Async flow (agentic compiler RFC)
async def analyze_flow(state: dict) -> dict:
    state["results"] = [await research_agent(state["tasks"][i]) for i in range(len(state["tasks"]))]
    return state

# Async flow with true local parallelism
async def analyze_flow(state: dict) -> dict:
    state["results"] = await asyncio.gather(
        *(research_agent({"task": t}) for t in state["tasks"])
    )
    return state
```

All three patterns require the same distributed infrastructure:
1. **Fan-out**: Split payload into N slices, send to N sub-agents in parallel
2. **Fan-in**: Collect N results, merge back into parent payload
3. **Continuation**: Resume parent workflow with merged results

### Three Syntax Levels

The Flow DSL supports three syntax levels for fan-out. All compile to the **same** distributed fan-out/fan-in on Asya — the difference is only in local execution semantics:

| Syntax | Local Execution | Compiled Asya | Flow Type |
|---|---|---|---|
| `[actor(x) for x in items]` | Sequential (sync) | Parallel fan-out (compiler optimization) | Sync `def` |
| `[await actor(x) for x in items]` | Sequential (async, one at a time) | Parallel fan-out (compiler optimization) | Async `def` |
| `await asyncio.gather(*(actor(x) for x in items))` | Parallel (async, concurrent on event loop) | Parallel fan-out | Async `def` |

**Compiler optimization**: The compiler recognizes that list comprehensions with actor calls have no data dependencies between iterations. Since each actor call is independent, the compiler automatically promotes them to parallel fan-out on Asya — even though they run sequentially locally. This is analogous to how a C compiler can auto-vectorize a loop.

The user chooses the syntax based on their local execution needs. If local parallelism matters (e.g., for testing I/O-bound actors), use `asyncio.gather`. If not, the simpler list comprehension syntax works and still gets distributed parallelism on Asya.

### Design Principles

1. **Separation of Concerns**: Fan-out is a FLOW concern (routers), NOT an actor concern
   - Payload-mode actors CANNOT fan-out
   - Only envelope-mode routers manipulate routes
   - Fan-out routers use `yield` (generators) to emit multiple messages — the legacy list-return fan-out is being removed (see asya-51j1)
   - Clear boundary: actors process, routers route

2. **Pure Python Flows**: Flow code must run as regular Python (sync or async)
   - No asya pip package imports, only stdlib (`asyncio`, `typing`)
   - Sync flows: list comprehensions for fan-out
   - Async flows: `await` list comprehensions or `asyncio.gather` for fan-out
   - Complexity solved via documentation + visualization

3. **Dynamic N**: Fan-out count determined at runtime from payload values
   - Static fan-out (fixed N) is a special case
   - Updates RFC asya-bi8's ParallelAgent to support dynamic case

4. **CPS Integration**: Fan-out/fan-in is an extension of the agentic compiler's CPS transformation
   - List comprehensions and `asyncio.gather` both produce `FanOutCall` IR nodes
   - The aggregator is the continuation point after all gather branches complete


**Key architectural decisions captured**:
- Fan-out is a FLOW concern (routers), not actor concern
- Aggregator does heavy lifting, CDC just emits
- Three syntax levels, one compilation target (distributed fan-out)
- List comprehension fan-out is a compiler optimization (sequential locally, parallel on Asya)
- ADK event model (partial field classification)
---

## Flow DSL Syntax

### Syntax Level 1: Sync List Comprehension

For sync flows (existing compiler), list comprehensions with actor calls are recognized as fan-out:

```python
def analyze_flow(p: dict) -> dict:
    p = validate_input(p)

    # Fan-out: sequential locally, parallel on Asya (compiler optimization)
    p["results"] = [analyze_task(p["tasks"][i]) for i in range(len(p["tasks"]))]

    p = summarize_results(p)
    return p
```

**Local**: Each `analyze_task` call runs one after another.
**Asya**: Compiler detects independent iterations, compiles to parallel fan-out.

### Syntax Level 2: Async List Comprehension

For async flows (agentic compiler RFC), `await` inside list comprehensions:

```python
async def analyze_flow(state: dict) -> dict:
    state = await validate_input(state)

    # Fan-out: sequential locally (one await at a time), parallel on Asya
    state["results"] = [await analyze_task(state["tasks"][i]) for i in range(len(state["tasks"]))]

    state = await summarize_results(state)
    return state
```

**Local**: Each `await analyze_task(...)` completes before the next starts.
**Asya**: Same compilation as sync — independent iterations become parallel fan-out.

### Syntax Level 3: `asyncio.gather`

For async flows where local parallelism is desired:

```python
import asyncio

async def analyze_flow(state: dict) -> dict:
    state = await validate_input(state)

    # Fan-out: parallel locally AND on Asya
    state["results"] = await asyncio.gather(
        *(analyze_task({"task": state["tasks"][i]}) for i in range(len(state["tasks"])))
    )

    state = await summarize_results(state)
    return state
```

**Local**: All `analyze_task` coroutines run concurrently on the event loop.
**Asya**: Same distributed fan-out as levels 1 and 2.

### When to Use Which

| Use Case | Recommended Syntax |
|---|---|
| Simple sync flow, don't care about local performance | Level 1: `[actor(x) for x in items]` |
| Async flow, actors have side effects or ordering needs locally | Level 2: `[await actor(x) for x in items]` |
| Async flow, want local parallelism for I/O-bound actors (testing, dev) | Level 3: `asyncio.gather(...)` |
| Heterogeneous parallel calls (different actors) | Level 3: `asyncio.gather(a(s), b(s), c(s))` |

### Supported `asyncio.gather` Patterns

```python
import asyncio

async def flow(state: dict) -> dict:
    items = state["items"]

    # Pattern 1: Dynamic fan-out with generator expression
    state["results"] = await asyncio.gather(
        *(process_item({"item": item}) for item in items)
    )

    # Pattern 2: Static fan-out (fixed N, heterogeneous actors)
    summary, analysis, review = await asyncio.gather(
        summarize(state),
        analyze(state),
        review(state),
    )
    state["summary"] = summary
    state["analysis"] = analysis
    state["review"] = review

    # Pattern 3: Error handling with return_exceptions
    state["results"] = await asyncio.gather(
        *(risky_call({"item": item}) for item in items),
        return_exceptions=True,
    )

    return state
```

### Generator Syntax for Streaming (Future)

For streaming partial results during fan-out:

```python
async def streaming_analyze(state: dict) -> dict:
    async for result in fan_out_stream(state["tasks"]):
        yield result  # Stream partial to gateway
    # After loop: all results available
    return state
```

### Compilation

All three syntax levels compile to the same distributed infrastructure:
1. Fan-out router (emits N+1 messages)
2. Sub-agent actors (process slices)
3. Aggregator crew actor (collects results)
4. Continuation router (resumes after fan-in)

The compiler detects fan-out opportunities by analyzing:
- **List comprehensions**: `[actor(expr) for var in iterable]` — checks that each iteration is independent (no cross-iteration data dependencies)
- **`asyncio.gather`**: `await asyncio.gather(*(actor(expr) for var in iterable))` — explicit parallel intent

Both produce the same `FanOutCall` IR node.

### New IR Node

Extending the agentic compiler's IR (`src/asya-cli/asya_cli/flow/ir.py`):

```python
@dataclass
class FanOutCall(IROperation):
    """A fan-out/fan-in operation detected from list comprehension or asyncio.gather.

    Sources:
    - [actor(x) for x in items]                      (sync comprehension)
    - [await actor(x) for x in items]                 (async comprehension)
    - await asyncio.gather(*(actor(x) for x in items)) (explicit gather)

    All three compile to the same distributed fan-out. The compiler generates:
    - A fan-out router that emits N+1 messages (1 setup + N slices)
    - An aggregator crew actor reference
    - A continuation router after all results are collected
    """
    assign_to: str              # Variable receiving results (e.g., "state['results']")
    actor_name: str             # Actor called in each iteration (e.g., "analyze_task")
    iterable_expr: str          # Source expression (e.g., "state['tasks']")
    slice_expr: str             # Per-item payload expression (e.g., '{"task": item}')
    syntax: str                 # "comprehension" | "async_comprehension" | "gather"
    is_static: bool = False     # True for fixed-N heterogeneous gather
    static_calls: list = None   # For static gather: list of (actor_name, arg_expr) tuples
    return_exceptions: bool = False  # Whether return_exceptions=True is set (gather only)
```

This integrates with the existing `AwaitCall`, `WhileLoop`, and `YieldEvent` IR nodes from the agentic compiler RFC.

---

## Fan-Out Architecture

### Message Pattern: Setup + N Slices

Fan-out router emits **N+1 messages total**:

```
+--------------+
|  Fan-out     |
|  Router      |
+------+-------+
       |
       +-------> Aggregator: "expect 5 slices for parent_id=xyz"
       |
       +-------> Sub-agent 1: slice[0] only
       +-------> Sub-agent 2: slice[1] only
       +-------> Sub-agent 3: slice[2] only
       +-------> Sub-agent 4: slice[3] only
       +-------> Sub-agent 5: slice[4] only
                    |
                    v
              Aggregator (crew actor)
              - Receives 6 messages total
              - Stores in Postgres
              - CDC detects "complete" (all 6 arrived)
              - Emits merged payload
```

### Setup Message

Contains full context for aggregation:

```python
# Setup message emitted by fan-out router
{
    "route": {
        "actors": ["start", "fan_out_router", "aggregator", "post_process", "end"],
        "current": 2  # Points to aggregator
    },
    "payload": {
        "original_payload": {...},  # Full parent payload
        "expected_count": 5,
        "result_field": "results"   # Where to place merged results
    },
    "parent_id": "envelope-xyz"
}
```

### Slice Messages

Minimal payload, short route:

```python
# Slice message (one per sub-agent)
{
    "route": {
        "actors": ["analyze_task", "aggregator"],
        "current": 0  # Points to sub-agent
    },
    "headers": {
        "slice_index": 0,
        "total_slices": 5
    },
    "payload": {"task": "research topic A"},  # Just the slice!
    "parent_id": "envelope-xyz"
}
```

### Router Does Slicing

The router extracts and sends minimal payload per slice:
- Runtime unchanged - receives dict payload as normal
- Keeps runtime simple
- Router has the slicing logic from compiled flow

### Static Fan-Out (Heterogeneous Gather)

For static `asyncio.gather` with different actors:

```python
summary, analysis, review = await asyncio.gather(
    summarize(state),
    analyze(state),
    review(state),
)
```

The fan-out router emits 4 messages:
- Setup: `{expected_count: 3, result_fields: ["summary", "analysis", "review"]}`
- Slice 0: route to `summarize`, headers: `{slice_index: 0}`
- Slice 1: route to `analyze`, headers: `{slice_index: 1}`
- Slice 2: route to `review`, headers: `{slice_index: 2}`

---

## Fan-In Aggregator Design

### Pre-Increment + Pre-Merge Pattern

**Key insight**: Aggregator does all heavy lifting BEFORE writing to DB. CDC is trivial.

```
+-------------------------------------------------------------------------+
|  STEP 1: Fan-out router emits N+1 messages                              |
+-------------------------------------------------------------------------+
|                                                                         |
|  Setup message:                                                         |
|  route: ["start", "fan_out_router", "aggregator", "post_process", "end"]|
|  current: 2 (pointing at aggregator)                                    |
|  payload: {original_payload, expected_count: 3, result_field: "results"}|
|                                                                         |
|  Slice messages (x3):                                                   |
|  route: ["aggregator"], current: 0                                      |
|  payload: {slice_data}                                                  |
|                                                                         |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
|  STEP 2: Aggregator pre-processes BEFORE writing to DB                  |
+-------------------------------------------------------------------------+
|                                                                         |
|  For setup message:                                                     |
|  - Increment current: 2 -> 3 (now points to "post_process")            |
|  - Save route + payload skeleton to DB                                  |
|                                                                         |
|  For slice messages:                                                    |
|  - Pre-merge into payload: results[slice_index] = slice_payload         |
|  - (route ignored, just merge data)                                     |
|                                                                         |
+-------------------------------------------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
|  STEP 3: CDC detects completeness, emits AS-IS                          |
+-------------------------------------------------------------------------+
|                                                                         |
|  DB already contains:                                                   |
|  route: ["start", "fan_out_router", "aggregator", "post_process", "end"]|
|  current: 3 (ready for post_process!)                                   |
|  payload: {original_payload, results: [r1, r2, r3]}  (fully merged!)   |
|                                                                         |
|  CDC just: SELECT * WHERE complete -> emit -> done                      |
|                                                                         |
+-------------------------------------------------------------------------+
```

### Aggregator Actor (Crew)

Simple actor that writes to database:

```python
async def aggregator(envelope: dict) -> dict:
    parent_id = envelope.get("parent_id") or envelope["id"]
    is_setup = "expected_count" in envelope["payload"]

    if is_setup:
        # Increment route.current for continuation
        route = envelope["route"].copy()
        route["current"] += 1

        await db.execute("""
            INSERT INTO fan_in_state
            (parent_id, route, payload, expected_count, received_count)
            VALUES ($1, $2, $3, $4, 1)
        """, parent_id, json.dumps(route),
             json.dumps(envelope["payload"]),
             envelope["payload"]["expected_count"])
    else:
        # Pre-merge slice into existing payload
        slice_index = envelope["headers"]["slice_index"]
        slice_data = envelope["payload"]

        await db.execute("""
            UPDATE fan_in_state
            SET payload = jsonb_set(
                payload,
                ARRAY['results', $2::text],
                $3::jsonb
            ),
            received_count = received_count + 1
            WHERE parent_id = $1
        """, parent_id, str(slice_index), json.dumps(slice_data))

    return {}  # Empty = no routing, message acked
```

### CDC Process

Separate process detects completeness and emits:

```sql
-- Detect complete aggregations
SELECT parent_id, route, payload
FROM fan_in_state
WHERE received_count = expected_count + 1  -- Setup + N slices
  AND emitted = false;

-- After emit, mark as processed
UPDATE fan_in_state SET emitted = true WHERE parent_id = $1;
```

**Note**: Specific Postgres CDC implementation (LISTEN/NOTIFY, logical replication, Debezium) requires separate research.

---

## Async Generator Streaming

### ADK-Compliant Event Model

Handlers use async generators with ADK's event classification:

```python
async def research_agent(task: str):
    yield {"partial": True, "content": {"parts": [{"text": "Thinking..."}]}}
    yield {"partial": True, "content": {"parts": [{"text": "Found results..."}]}}
    yield {"partial": False, "content": {"parts": [{"text": "Final answer"}]}}
    # No return - last yield with partial=False is the control event
```

**Event Classification**:
- `partial: true` -> Streaming event -> Gateway -> User (SSE)
- `partial: false` or absent -> Complete event -> Next actor (queue)
- `actions.transfer_to_agent` -> Control signal (route to another agent)
- `actions.escalate` -> Control signal (exit loop)

### Message Flow with Streaming

```
+-----------------------------------------------------------------+
|  1. Sidecar receives message from queue (NOT acked yet)         |
|  2. Sidecar sends envelope to runtime via Unix socket           |
|  3. Runtime calls async generator handler                       |
|  4. Handler yields events:                                      |
|     +- yield {partial: true, ...}  -> Sidecar -> Gateway (SSE)  |
|     +- yield {partial: true, ...}  -> Sidecar -> Gateway (SSE)  |
|     +- yield {partial: false, ...} -> Sidecar -> Next queue     |
|  5. Generator exhausts (StopIteration)                          |
|  6. Runtime sends "end" event to sidecar                        |
|  7. Sidecar acks original message                               |
|  8. Sidecar pulls next message                                  |
+-----------------------------------------------------------------+
```

**Key properties**:
- Message NOT acked until ALL events processed
- At-least-once semantics preserved
- Clear signal when generator is done

### Fan-Out with Multiple Control Events

For fan-out, router yields multiple `partial: false` events:

```python
async def fan_out_router(envelope: dict):
    items = envelope["payload"]["items"]
    n = len(items)
    parent_id = envelope["id"]

    # Setup message (control event)
    yield {
        "partial": False,
        "route": {"actors": [..., "aggregator", ...], "current": 2},
        "payload": {"expected_count": n, ...},
        "parent_id": parent_id
    }

    # Slice messages (control events)
    for i, item in enumerate(items):
        yield {
            "partial": False,
            "route": {"actors": ["sub_agent", "aggregator"], "current": 0},
            "headers": {"slice_index": i},
            "payload": item,
            "parent_id": parent_id
        }

    # Generator exhausts -> runtime sends "end" -> sidecar acks
```

Sidecar sends each `partial: false` event to its queue immediately (no batching).

---

## Sub-Agent Context Isolation

### Clean Slate for Sub-Problems

Sub-agents receive **minimal payload** with NO parent context:

```
+---------------------------------------------------------+
|  Parent Agent Context                                    |
|  - Full conversation history                             |
|  - Session state                                         |
|  - User preferences                                      |
+-----------------+---------------------------------------+
                  | Fan-out (slice only, NO context)
                  v
+---------------------------------------------------------+
|  Sub-Agent or Tool (clean slate)                        |
|  - Just the task: {"location": "NYC"}                   |
|  - No parent history                                    |
|  - Returns: {"weather": "72F"}                          |
+---------------------------------------------------------+
```

**Rationale**:
- In agentic Asya, context = message/conversation history stored in payload
- Sub-agents solving sub-problems don't need parent's conversation
- Keeps slice messages small and focused
- Prevents context pollution between parallel sub-agents

---

## Implementation Details

### Database Schema

```sql
CREATE TABLE fan_in_state (
    parent_id       TEXT PRIMARY KEY,
    route           JSONB NOT NULL,          -- Pre-incremented route
    payload         JSONB NOT NULL,          -- Pre-merged payload
    expected_count  INTEGER NOT NULL,
    received_count  INTEGER DEFAULT 0,
    emitted         BOOLEAN DEFAULT false,
    created_at      TIMESTAMP DEFAULT now(),
    updated_at      TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_fan_in_complete ON fan_in_state (parent_id)
    WHERE received_count = expected_count + 1 AND emitted = false;
```

### Flow Compiler Changes

The flow compiler must:

1. **Detect fan-out patterns** in all three syntax levels:
   ```python
   # Sync comprehension
   p["results"] = [analyze_task(p["tasks"][i]) for i in range(len(p["tasks"]))]
   # Async comprehension
   state["results"] = [await analyze_task(state["tasks"][i]) for i in range(len(state["tasks"]))]
   # asyncio.gather
   state["results"] = await asyncio.gather(
       *(analyze_task({"task": t}) for t in state["tasks"])
   )
   ```

2. **Emit `FanOutCall` IR node** that captures:
   - Assignment target (`state["results"]`)
   - Actor name (`analyze_task`)
   - Iterable expression (`state["tasks"]`)
   - Per-item payload expression (`{"task": t}`)
   - Syntax variant (`comprehension` / `async_comprehension` / `gather`)

3. **Grouper: transform `FanOutCall` into**:
   - Fan-out router (emits setup + N slice messages)
   - Aggregator actor reference inserted into route
   - Continuation router (receives merged payload, resumes flow)

4. **Handle static gather** (heterogeneous actors):
   ```python
   a, b, c = await asyncio.gather(actor_x(state), actor_y(state), actor_z(state))
   ```
   - Each branch routes to a different actor
   - Aggregator merges by slice index into ordered tuple

### CPS Integration

`FanOutCall` integrates with the agentic compiler's CPS transformation:

```
                      User's flow (.py)
                         sync or async
                              |
                              v
                    +------------------+
                    |  Parser (AST)    |  Detect: list comprehensions,
                    |                  |  async def, await, while,
                    |                  |  yield, asyncio.gather
                    +--------+---------+
                             |
                             v
                    +------------------+
                    |  IR Operations   |  ActorCall, AwaitCall,
                    |                  |  WhileLoop, YieldEvent,
                    |                  |  FanOutCall
                    +--------+---------+
                             |
                             v
                    +------------------+
                    |    Grouper       |  CPS split at await boundaries
                    |  (CPS Engine)    |  FanOut -> fan-out + aggregator
                    +--------+---------+
                             |
                             v
                    +------------------+
                    |  Router Graph    |  Entry, continuation, fan-out,
                    |                  |  dispatch, collect, end
                    +--------+---------+
                             |
                     +-------+-------+
                     v               v
            +---------------+  +---------------+
            |  CodeGen      |  |  DotGen       |
            |  (routers.py) |  |  (flow.dot)   |
            +---------------+  +---------------+
```

### Runtime Changes

1. **Async handler support**: Detect `async def` handlers, run with `asyncio.run()`
2. **Async generator support**: Detect generator handlers, iterate and forward events
3. **End event emission**: Send `{"type": "end"}` when generator exhausts
4. **Streaming classification**: Forward `partial: true` to gateway, `partial: false` to queue

### Sidecar Changes

1. **Event classification**: Read `partial` field to determine routing
2. **Multiple control events**: Send each to appropriate queue immediately
3. **End event handling**: Ack message only after receiving end event
4. **Gateway streaming**: HTTP POST partial events to gateway for SSE

---

## Open Questions

### 1. Postgres CDC Implementation

Which approach for detecting completeness?
- LISTEN/NOTIFY with trigger
- Logical replication + Debezium
- Polling with efficient index
- pg_notify from trigger

### 2. Failure Handling

- What if sub-agent fails? Retry? Partial results?
- Timeout for aggregation (some slices never arrive)?
- Idempotency for duplicate slices?
- How does `return_exceptions=True` map to distributed execution? (Partial success vs all-or-nothing)

### 3. Nested Fan-Out

- Can a sub-agent itself fan-out (nested `asyncio.gather`)?
- How to track parent_id hierarchy?
- Aggregator coordination across levels?

### 4. Tool-Style Signatures

How do typed handler signatures work with slicing?

```python
def analyze(text: str) -> dict:  # Slice has {"text": "..."}
    return {"sentiment": "positive"}
```

See separate RFC: `asya-handler-signatures.md`

### 5. Ordering Guarantees

- `asyncio.gather` preserves input order in its result tuple
- Does the aggregator maintain slice order in the result array?
- What if slices complete out of order? (Aggregator uses `slice_index` for correct placement)

### 6. Payload Size in Gather

- Each slice gets a minimal payload (just the slice data)
- But the setup message carries the full original payload
- For large payloads, should we offload to S3/artifact storage?

---

## References

- [Agentic Compiler RFC](../agentic-compiler/agentic-compiler-rfc.md) -- Async/await CPS transformation
- [ADK Events Documentation](https://google.github.io/adk-docs/events/)
- [A2A Protocol](https://a2a-protocol.org/)
- [Asya Flow DSL](../../architecture/asya-flow.md)
- [Agentic Asya RFC](../asya-bi8-agentic-asya.md)
- [Handler Signatures RFC](../asya-handler-signatures.md)
- [PEP 525 -- Asynchronous Generators](https://peps.python.org/pep-0525/)
- [asyncio.gather documentation](https://docs.python.org/3/library/asyncio-task.html#asyncio.gather)

---

## Appendix: Complete Flow Example

### Input Flow (Three Equivalent Syntaxes)

**Sync (Level 1)** — simplest, sequential locally:
```python
def research_flow(p: dict) -> dict:
    p = validate_topics(p)
    p["findings"] = [research_agent(p["topics"][i]) for i in range(len(p["topics"]))]
    p = synthesize_findings(p)
    return p
```

**Async sequential (Level 2)** — async, but one-at-a-time locally:
```python
async def research_flow(state: dict) -> dict:
    state = await validate_topics(state)
    state["findings"] = [await research_agent(state["topics"][i]) for i in range(len(state["topics"]))]
    state = await synthesize_findings(state)
    return state
```

**Async parallel (Level 3)** — true concurrency locally:
```python
import asyncio

async def research_flow(state: dict) -> dict:
    state = await validate_topics(state)
    state["findings"] = await asyncio.gather(
        *(research_agent({"topic": topic}) for topic in state["topics"])
    )
    state = await synthesize_findings(state)
    return state
```

All three compile to the **same** distributed actor network below. The Level 3 version additionally runs with true concurrency when executed locally via `asyncio.run(research_flow({"topics": ["AI", "ML", "DL"]}))`.

### Compiled Actors

1. **entry_research_flow** (router): Validates, routes to fan-out
2. **fan_out_research_flow** (router): Emits N+1 messages
3. **research_agent** (actor): Processes single topic
4. **aggregator** (crew): Collects results in Postgres
5. **continuation_after_gather** (router): Restores payload, routes to synthesize
6. **synthesize_findings** (actor): Combines all findings
7. **end_research_flow** (router): Completes flow

### Message Flow

```
Input: {"topics": ["AI", "ML", "DL"]}

1. entry_research_flow
   -> validate_topics
   -> fan_out_research_flow

2. fan_out_research_flow emits 4 messages:
   - Setup: {expected_count: 3, original_payload: {...}}
   - Slice 0: {payload: {"topic": "AI"}}
   - Slice 1: {payload: {"topic": "ML"}}
   - Slice 2: {payload: {"topic": "DL"}}

3. research_agent (x3, parallel)
   - Each processes one topic
   - Each routes to aggregator

4. aggregator receives 4 messages:
   - Stores setup with pre-incremented route
   - Pre-merges each slice result

5. CDC detects completeness
   - Emits merged envelope
   - route.current points to continuation_after_gather

6. continuation_after_gather
   - Restores: state["findings"] = [r1, r2, r3]
   - Routes to synthesize_findings

7. synthesize_findings
   - Receives: {findings: [r1, r2, r3], topics: [...]}
   - Produces: {summary: "..."}

8. end_research_flow
   - Completes, routes to happy-end
```

---

## Appendix: Gather + ReAct Loop Example

Combining `asyncio.gather` (this RFC) with `while` loops (agentic compiler RFC):

```python
import asyncio
from typing import AsyncGenerator

async def parallel_research_agent(state: dict) -> AsyncGenerator[dict, None]:
    """A ReAct agent that can fan-out to multiple tools in parallel."""
    state["messages"] = state.get("messages", [
        {"role": "user", "content": state["query"]}
    ])

    while True:
        state = await llm_call(state)

        if state.get("tool_calls"):
            # Multiple tool calls -> parallel fan-out
            state["tool_results"] = await asyncio.gather(
                *(execute_tool({"call": tc}) for tc in state["tool_calls"])
            )

            # Append all tool results to messages
            for tc, result in zip(state["tool_calls"], state["tool_results"]):
                state["messages"].append({
                    "role": "tool",
                    "content": result["output"],
                    "tool_call_id": tc["id"],
                })
        else:
            yield {"type": "result", **state}
            return
```

This compiles to a network with:
- A ReAct loop (while + dispatch router + loop-back) from the agentic compiler
- A nested fan-out/fan-in (gather + aggregator) from this RFC
- Both working together: the loop iterates, and within each iteration, tool calls fan out in parallel

---

**End of Document**
