---
title: "Research: event compaction and context window management for long-running agents"
priority: 3 # low
tags:
  - type:research
---

Research how to manage conversation history and context window limits for
long-running agentic flows, equivalent to ADK's event compaction.

## ADK Pattern

ADK supports automatic event compaction via `EventCompaction`:

```python
# ADK: Runner compacts events after invocation completes
if self.app and self.app.events_compaction_config:
    await _run_compaction_for_sliding_window(...)

class EventCompaction(BaseModel):
    start_timestamp: float     # compacted range start
    end_timestamp: float       # compacted range end
    compacted_content: Content # summarized content replacing the range
```

When the conversation history exceeds a configured limit, ADK:
1. Takes a window of old events
2. Calls the LLM to summarize them into a single compacted content
3. Replaces the original events with the compaction summary
4. Late-joining queries only see the compacted version

See survey-adk-data-flow.md Section 2.3 (`compaction` field in EventActions).

## Asya Challenge

In Asya, there is no central "conversation history" -- state travels in the
message payload. Long-running agentic loops (ReAct with many tool calls) will
accumulate large payloads as message history grows:

```python
state["messages"] = [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "...", "tool_calls": [...]},
    {"role": "tool", "content": "..."},
    # ... hundreds of messages over many loop iterations
]
```

Eventually the payload exceeds queue message size limits (SQS: 256KB) or the
LLM context window.

## Approaches to Research

### A. Actor-level compaction

A dedicated "compactor" actor in the loop that periodically summarizes the
message history:

```python
async def react_with_compaction(state: dict) -> dict:
    while True:
        if len(state["messages"]) > THRESHOLD:
            state = await compactor(state)  # summarize old messages
        state = await llm_call(state)
        if not state.get("tool_calls"):
            break
        state = await tool_executor(state)
    return state
```

### B. Handler-level sliding window

The LLM handler itself manages its context window by keeping only the last N
messages and a running summary:

```python
async def llm_handler(state: dict) -> dict:
    messages = state["messages"]
    if len(messages) > MAX_MESSAGES:
        summary = await summarize(messages[:-KEEP_RECENT])
        state["messages"] = [{"role": "system", "content": summary}] + messages[-KEEP_RECENT:]
    # ... call LLM with truncated history
```

### C. State proxy with versioned history

Use the state proxy (epic 1dmf, S3-backed) to store full history externally,
keeping only a reference and sliding window in the payload:

```python
state["_history_ref"] = "s3://bucket/task-123/history.json"
state["messages"] = state["messages"][-10:]  # only recent in payload
```

### D. Queue-aware payload splitting

For large payloads approaching queue limits, automatically split the payload
into a reference (in the queue message) and the full data (in S3):

```json
{
  "payload": {"_ref": "s3://bucket/task-123/payload.json"},
  "route": {...}
}
```

The sidecar transparently resolves the reference before delivering to the runtime.

## Questions to Resolve

1. Should compaction be a framework feature (automatic) or a handler concern
   (manual)? ADK does it automatically; Asya's distributed model may require
   explicit actor-level compaction.
2. What is the right threshold for compaction? Token count? Message count?
   Payload size?
3. Should the state proxy (S3) be used for overflow, or should we enforce
   payload discipline (keep payloads small)?
4. How does compaction interact with fan-out/fan-in? Each branch may need
   independent compaction.

## Related Infrastructure

- Epic 1dmf (stateful actors -- S3 state proxy, closed)
- Epic 1cma (envelope compression -- zlib for large envelopes)
- Task 1i5p (media storage abstraction)
- SQS message size limit: 256KB
- RabbitMQ message size limit: configurable (default 128MB)

## References

- survey-adk-data-flow.md Section 2.3 (EventCompaction), Section 8.1 (#15)
- epic 1dmf (stateful actors, S3 state proxy)
- task 1cma/1f9ag5 (zlib compression for large envelopes)
