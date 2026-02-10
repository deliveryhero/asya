# RFC: Stateful Fan-In/Fan-Out for Agentic Workflows

**Status**: Draft
**Author**: Architecture Discussion
**Date**: 2026-01-28
**Related**: asya-bi8-agentic-asya.md, asya-handler-signatures.md

---

## Executive Summary

This RFC defines the design for stateful fan-in/fan-out in Asya, enabling dynamic parallel execution of sub-agents with result aggregation. The design uses a CDC-based aggregator crew actor connected to PostgreSQL (with future support for Redis/NoSQL) that waits for all N parallel fan-out messages to arrive, assembles the result, and emits the merged payload.

**Key Innovations**:
- **Dynamic fan-out**: N determined at runtime from payload values
- **Setup + slice message pattern**: N+1 messages total (1 setup, N slices)
- **Pre-increment + pre-merge**: Aggregator prepares envelope before DB write, CDC emits as-is
- **ADK-compliant streaming**: Async generators with `partial` field classification
- **Pure Python Flow DSL**: List comprehensions and generators compile to choreography

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
p["sub_agents_results"] = [research_agent(p["tasks"][i]) for i in range(len(p["tasks"]))]
```

For async handlers, the syntax would be:
```python
p["sub_agents_results"] = asyncio.gather(*[
    research_agent(p["tasks"][i]) for i in range(len(p["tasks"]))
])
```

This pattern requires:
1. **Fan-out**: Split payload into N slices, send to N sub-agents in parallel
2. **Fan-in**: Collect N results, merge back into parent payload
3. **Continuation**: Resume parent workflow with merged results

### Design Principles

1. **Separation of Concerns**: Fan-out is a FLOW concern (routers), NOT an actor concern
   - Payload-mode actors CANNOT fan-out
   - Only envelope-mode routers manipulate routes
   - Clear boundary: actors process, routers route

2. **Pure Python Flows**: Flow code must run as regular Python
   - No asya pip package imports
   - Only stdlib functions or native Python syntax
   - Complexity solved via documentation + visualization

3. **Dynamic N**: Fan-out count determined at runtime from payload values
   - Static fan-out (fixed N) is a special case
   - Updates RFC asya-bi8's ParallelAgent to support dynamic case


**Key architectural decisions captured**:
- Fan-out is a FLOW concern (routers), not actor concern
- Aggregator does heavy lifting, CDC just emits
- Pure Python flows with list comprehensions
- ADK event model (partial field classification)
---

## Flow DSL Syntax

### List Comprehension Fan-Out

The Flow DSL uses standard Python list comprehensions:

```python
def analyze_flow(p: dict) -> dict:
    # Sequential pre-processing
    p = validate_input(p)

    # Fan-out: N determined by len(p["tasks"])
    p["results"] = [analyze_task(p["tasks"][i]) for i in range(len(p["tasks"]))]

    # Sequential post-processing (after all results collected)
    p = summarize_results(p)

    return p
```

### Generator Syntax (Future)

For streaming partial results during fan-out:

```python
def streaming_analyze(p: dict) -> dict:
    for result in (analyze_task(task) for task in p["tasks"]):
        yield result  # Stream partial to gateway
    # After loop: all results available
    return p
```

### Compilation

The flow compiler transforms list comprehensions into:
1. Fan-out router (emits N+1 messages)
2. Sub-agent actors (process slices)
3. Aggregator crew actor (collects results)
4. Continuation to post-processing

---

## Fan-Out Architecture

### Message Pattern: Setup + N Slices

Fan-out router emits **N+1 messages total**:

```
┌──────────────┐
│  Fan-out     │
│  Router      │
└──────┬───────┘
       │
       ├──────► Aggregator: "expect 5 slices for parent_id=xyz"
       │
       ├──────► Sub-agent 1: slice[0] only
       ├──────► Sub-agent 2: slice[1] only
       ├──────► Sub-agent 3: slice[2] only
       ├──────► Sub-agent 4: slice[3] only
       └──────► Sub-agent 5: slice[4] only
                    │
                    ▼
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

---

## Fan-In Aggregator Design

### Pre-Increment + Pre-Merge Pattern

**Key insight**: Aggregator does all heavy lifting BEFORE writing to DB. CDC is trivial.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 1: Fan-out router emits N+1 messages                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Setup message:                                                         │
│  route: ["start", "fan_out_router", "aggregator", "post_process", "end"]│
│  current: 2 (pointing at aggregator)                                    │
│  payload: {original_payload, expected_count: 3, result_field: "results"}│
│                                                                         │
│  Slice messages (x3):                                                   │
│  route: ["aggregator"], current: 0                                      │
│  payload: {slice_data}                                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 2: Aggregator pre-processes BEFORE writing to DB                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  For setup message:                                                     │
│  - Increment current: 2 → 3 (now points to "post_process")              │
│  - Save route + payload skeleton to DB                                  │
│                                                                         │
│  For slice messages:                                                    │
│  - Pre-merge into payload: results[slice_index] = slice_payload         │
│  - (route ignored, just merge data)                                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STEP 3: CDC detects completeness, emits AS-IS                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  DB already contains:                                                   │
│  route: ["start", "fan_out_router", "aggregator", "post_process", "end"]│
│  current: 3 (ready for post_process!)                                   │
│  payload: {original_payload, results: [r1, r2, r3]}  (fully merged!)    │
│                                                                         │
│  CDC just: SELECT * WHERE complete → emit → done                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
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
- `partial: true` → Streaming event → Gateway → User (SSE)
- `partial: false` or absent → Complete event → Next actor (queue)
- `actions.transfer_to_agent` → Control signal (route to another agent)
- `actions.escalate` → Control signal (exit loop)

### Message Flow with Streaming

```
┌─────────────────────────────────────────────────────────────────┐
│  1. Sidecar receives message from queue (NOT acked yet)         │
│  2. Sidecar sends envelope to runtime via Unix socket           │
│  3. Runtime calls async generator handler                       │
│  4. Handler yields events:                                      │
│     ├─ yield {partial: true, ...}  → Sidecar → Gateway (SSE)   │
│     ├─ yield {partial: true, ...}  → Sidecar → Gateway (SSE)   │
│     └─ yield {partial: false, ...} → Sidecar → Next queue      │
│  5. Generator exhausts (StopIteration)                          │
│  6. Runtime sends "end" event to sidecar                        │
│  7. Sidecar acks original message                               │
│  8. Sidecar pulls next message                                  │
└─────────────────────────────────────────────────────────────────┘
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

    # Generator exhausts → runtime sends "end" → sidecar acks
```

Sidecar sends each `partial: false` event to its queue immediately (no batching).

---

## Sub-Agent Context Isolation

### Clean Slate for Sub-Problems

Sub-agents receive **minimal payload** with NO parent context:

```
┌─────────────────────────────────────────────────────────────┐
│  Parent Agent Context                                        │
│  - Full conversation history                                 │
│  - Session state                                             │
│  - User preferences                                          │
└───────────────┬─────────────────────────────────────────────┘
                │ Fan-out (slice only, NO context)
                ▼
┌─────────────────────────────────────────────────────────────┐
│  Sub-Agent or Tool (clean slate)                            │
│  - Just the task: {"location": "NYC"}                       │
│  - No parent history                                        │
│  - Returns: {"weather": "72°F"}                             │
└─────────────────────────────────────────────────────────────┘
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

1. **Detect list comprehensions** with actor calls:
   ```python
   p["results"] = [actor(p["items"][i]) for i in range(len(p["items"]))]
   ```

2. **Generate fan-out router** that:
   - Emits setup message with full route and payload
   - Emits N slice messages with minimal payload
   - Inserts aggregator into route

3. **Generate continuation** after aggregator:
   - Next actors in original flow become continuation route

### Runtime Changes

1. **Async generator support**: Detect generator handlers, iterate and forward events
2. **End event emission**: Send `{"type": "end"}` when generator exhausts
3. **Streaming classification**: Forward `partial: true` to gateway, `partial: false` to queue

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

### 3. Nested Fan-Out

- Can a sub-agent itself fan-out?
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

- Are slices processed in order?
- Does result array maintain slice order?
- What if slices complete out of order?

---

## References

- [ADK Events Documentation](https://google.github.io/adk-docs/events/)
- [A2A Protocol](https://a2a-protocol.org/)
- [Asya Flow DSL](../architecture/asya-flow.md)
- [Agentic Asya RFC](asya-bi8-agentic-asya.md)
- [Handler Signatures RFC](asya-handler-signatures.md)

---

## Appendix: Complete Flow Example

### Input Flow

```python
def research_flow(p: dict) -> dict:
    # Validate input
    p = validate_topics(p)

    # Fan-out to research agents
    p["findings"] = [research_agent(p["topics"][i]) for i in range(len(p["topics"]))]

    # Synthesize results
    p = synthesize_findings(p)

    return p
```

### Compiled Actors

1. **start_research_flow** (router): Validates, routes to fan-out
2. **fan_out_research_flow** (router): Emits N+1 messages
3. **research_agent** (actor): Processes single topic
4. **aggregator** (crew): Collects results in Postgres
5. **synthesize_findings** (actor): Combines all findings
6. **end_research_flow** (router): Completes flow

### Message Flow

```
Input: {"topics": ["AI", "ML", "DL"]}

1. start_research_flow
   → validate_topics
   → fan_out_research_flow

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
   - route.current points to synthesize_findings

6. synthesize_findings
   - Receives: {findings: [r1, r2, r3], topics: [...]}
   - Produces: {summary: "..."}

7. end_research_flow
   - Completes, routes to happy-end
```

---

**End of Document**
