# RFC: Tool-Style Handler Signatures

**Status**: In Progress
**Author**: Architecture Discussion
**Date**: 2026-01-28
**Updated**: 2026-02-09
**Related**: asya-bi8-agentic-asya.md, asya-handler-syntax-comparisons.md

---

## Problem Statement

Asya currently requires handlers to use dict-based signatures:

```python
def process(p: dict) -> dict:
    return {"result": p["input"] * 2}
```

Agentic frameworks (ADK, LangChain, DSPy, LangGraph) use typed signatures:

```python
@tool
def get_weather(location: str) -> str:
    """Get weather for a location."""
    return fetch_weather(location)
```

**Goal**: Find the simplest interface that:
1. Is easy to learn and develop
2. Allows mechanical/trivial translation from ADK/DSPy/LangGraph/etc to Asya
3. Maintains pure Python (no Asya-specific imports required)
4. Flows are runnable as regular Python functions
5. Supports async handlers and event streaming

---

## Constraints

1. **Pure Python**: No `asya` pip package imports in handler code
2. **No external config**: No YAML/JSON schema files for mapping
3. **Runnable flows**: Flow functions must execute as regular Python
4. **Framework detection**: Support existing framework decorators (@tool, etc.)
5. **Streaming-ready**: Signature design must accommodate async generators

---

## Current State

### Asya Handler Modes

From `asya_runtime.py`:

- **Payload mode**: `def handler(p: dict) -> dict` - receives/returns payload only
- **Envelope mode**: `def handler(e: dict) -> dict` - receives/returns full envelope

Both require dict signatures. No typed parameter support. **Fully synchronous** -- no async/await, no generators, no streaming.

### Framework Signatures

**ADK** (plain function, no decorator):
```python
def get_weather(city: str) -> dict:
    """Retrieves current weather for a specified city."""
    return {"status": "success", "report": "Sunny, 25C"}
```

**LangGraph** (state-based, closest to Asya's payload mode):
```python
def call_model(state: MessagesState) -> dict:
    response = llm.invoke(state["messages"])
    return {"messages": [response]}
```

**LlamaIndex** (plain function, auto-wrapped):
```python
def multiply(a: float, b: float) -> float:
    """Multiply two numbers and returns the product"""
    return a * b
```

**OpenAI Agents SDK** (decorator + typed context):
```python
@function_tool
async def fetch_weather(city: str) -> str:
    """Fetch the weather for a given city."""
    return f"Sunny in {city}"
```

See `asya-handler-syntax-comparisons.md` for the full 14-framework survey.

---

## Framework Research Findings

### Universal Pattern

All 14 surveyed frameworks converge on:

```
Plain Python function + type hints + docstring = tool
```

Asya's `payload: dict` contract is the outlier. The closest analog across frameworks is **LangGraph**, where every node receives a shared state dict and returns a partial update:

```python
# LangGraph: def node(state: State) -> dict
# Asya:      def handler(payload: dict) -> dict
```

Both patterns pass the full state in, get partial updates out. LangGraph adds **reducers** (`Annotated[list, add]`) to control merge semantics (append vs overwrite) -- conceptually similar to Asya's enrichment pattern.

### State Injection Patterns

Multiple frameworks inject context/state via specially-named parameters auto-excluded from the tool schema:

| Framework | Magic Parameter | Injected Object |
|-----------|----------------|-----------------|
| Google ADK | `tool_context: ToolContext` | Session state, artifacts, memory |
| OpenAI Swarm | `context_variables` | Shared dict |
| OpenAI Agents SDK | `ctx: RunContextWrapper[T]` | Typed context |
| LlamaIndex | `ctx: Context` | Workflow context + store |
| Agno | `run_context: RunContext` | Session state dict |
| LangGraph | `state: Annotated[dict, InjectedState]` | Graph state |

### Output Key Naming

Only **Google ADK** explicitly names where an agent's output goes in shared state:

```python
story_agent = LlmAgent(
    name="StoryGenerator",
    output_key="current_story",  # → state["current_story"] = result
)
```

All other frameworks either return strings (to LLM), merge dicts (LangGraph), or use typed events (LlamaIndex).

---

## Explored Approaches

### Approach 1: Flow Structure Inference

The flow structure itself reveals input/output mapping:

```python
def my_flow(p: dict) -> dict:
    p["weather"] = get_weather(p["location"])
    return p
```

Compiler infers from AST:
- **Input**: `p["location"]` → extract `location` field
- **Output**: `p["weather"]` → place result in `weather` field
- **Handler**: `get_weather` → deploy as actor

**Pros**:
- No decorator needed
- Pure Python
- Mapping explicit in code

**Cons**:
- Complex AST analysis
- Doesn't work for standalone actors (not in flow)

### Approach 2: Framework Decorator Detection

Detect existing framework decorators:

```python
@tool  # ADK or LangChain decorator
def get_weather(location: str) -> str:
    return fetch_weather(location)
```

Runtime detects `@tool` and uses its introspection:
- ADK: `func.__wrapped__`, parameter schemas
- LangChain: `func.args_schema`

**Pros**:
- Zero migration effort for existing code
- Frameworks already solved the schema problem

**Cons**:
- Framework dependency for decorator
- Different frameworks have different metadata

### Approach 3: Type Hint Introspection

Use standard Python type hints:

```python
def get_weather(location: str, units: str = "celsius") -> str:
    return fetch_weather(location)
```

Runtime uses `inspect.signature()` to extract:
- Parameter names and types
- Default values
- Return type

**Pros**:
- Pure Python (no imports)
- Standard typing

**Cons**:
- Doesn't specify which payload field maps to which param
- Return value placement unclear

### Approach 4: Detection Hierarchy

Combine approaches with priority:

1. If `@tool` decorator present → use framework's schema
2. If typed signature → introspect and match payload fields by name
3. If `dict -> dict` → pass payload as-is (current behavior)

**Open question**: How to handle field name mismatches?
```python
# Payload has: {"loc": "NYC"}
# Handler expects: location: str
# How does runtime know loc → location?
```

---

## Fan-Out Slice Context

In fan-out scenarios, sub-agents receive minimal payload (just their slice):

```python
# Flow:
p["results"] = [analyze(p["items"][i]) for i in range(len(p["items"]))]

# Slice payload arriving at analyze actor:
{"id": 1, "text": "hello"}

# Handler:
def analyze(text: str) -> dict:
    return {"sentiment": classify(text)}
```

The flow compiler knows:
- Input: `p["items"][i]` (each element)
- Each element has structure `{"id": ..., "text": ...}`
- Handler expects `text: str`

**Can compiler generate extraction code?**
```python
# Generated router code:
text = slice_payload["text"]
result = analyze(text)
output_payload = {"sentiment": result}  # or result if already dict
```

---

## Async and Event Streaming

### Current Limitations

Asya's runtime is **fully synchronous**:

```python
# asya_runtime.py handler invocation (simplified)
payload = user_func(e["payload"])   # Blocking call, single response
```

- No `async def` support
- No generator/`yield` support
- No streaming channel from actor back to gateway
- All data must be returned in one response

This is a fundamental gap for agentic use cases where handlers need to:
- Stream partial LLM responses as they're generated
- Emit progress events during long-running tasks
- Yield tool call results incrementally
- Support human-in-the-loop (suspend/resume)

### How Frameworks Handle Streaming

#### Pattern A: Async Generator (ADK, LlamaIndex)

The handler is an async generator that yields events:

```python
# Google ADK -- agent._run_async_impl yields Event objects
async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
    async for event in self.llm.generate_content_async(request, stream=True):
        yield event  # Partial text, tool calls, etc.

# LlamaIndex -- workflow steps emit typed events
class JokeFlow(Workflow):
    @step
    async def generate_joke(self, ev: StartEvent) -> JokeEvent:
        async for chunk in self.llm.astream_complete(prompt):
            ctx.write_event_to_stream(ProgressEvent(msg=chunk.delta))
        return JokeEvent(joke=full_text)
```

#### Pattern B: Stream Object (OpenAI Agents SDK, Mastra)

The runner returns a stream object, not the handler itself:

```python
# OpenAI Agents SDK
result = Runner.run_streamed(agent, "Hello!")
async for event in result.stream_events():
    if event.type == "raw_response_event":
        ...  # Token-level streaming

# Mastra (TypeScript)
const stream = await agent.stream("What's the weather?");
for await (const chunk of stream.textStream) {
    process.stdout.write(chunk);
}
```

#### Pattern C: State Updates (LangGraph)

LangGraph streams by emitting state deltas after each node:

```python
# 5 streaming modes
for update in agent.stream(inputs, stream_mode="updates"):
    print(update)  # Partial state dict from each node

# Custom streaming from within nodes
from langgraph.types import get_stream_writer
def my_node(state: State):
    writer = get_stream_writer()
    writer({"progress": "50%"})  # Emit custom event mid-execution
    return {"result": "done"}
```

#### Pattern D: Event Bus (CrewAI, Agno)

Events are published to an observable bus, handlers subscribe:

```python
# CrewAI event bus
class MyListener(BaseEventListener):
    def setup_listeners(self, crewai_event_bus):
        @crewai_event_bus.on(LLMStreamChunkEvent)
        def on_chunk(source, event):
            print(event.chunk, end="")

# Agno streaming events
async for event in agent.arun("query", stream=True, stream_events=True):
    if event.event == RunEvent.run_content:
        print(event.content, end="")
```

### Streaming Signature Design for Asya

The core tension: how to express "this handler returns a final result AND emits intermediate events" in a Python type signature.

#### Option S1: Async Generator (yields events, final yield is result)

```python
from typing import AsyncGenerator

async def summarize(text: str) -> AsyncGenerator[dict, None]:
    """Summarize a document with progress updates."""
    for i, chunk in enumerate(split_into_chunks(text)):
        partial = await llm.complete(chunk)
        yield {"type": "progress", "chunk": i, "partial": partial}
    yield {"type": "result", "summary": combine(partials)}
```

**Pros**: Pure Python, standard typing, natural `async for` consumption
**Cons**: Return type is `AsyncGenerator[dict, None]`, not `str` -- loses the clean typed return. Last yield is semantically different from all others (result vs event). Runtime needs convention to distinguish final result from intermediate events.

#### Option S2: Sync Return + Separate Stream Channel

```python
def summarize(text: str) -> str:
    """Summarize a document. Streaming handled by framework."""
    return llm.complete(text)  # Framework streams LLM output automatically
```

The runtime/sidecar intercepts the LLM call and streams tokens automatically. Handler stays synchronous and simple. This requires framework-level integration with LLM providers.

**Pros**: Handler signature stays clean (`str -> str`), no async complexity
**Cons**: Only works for LLM streaming, not custom progress events. Requires deep framework integration.

#### Option S3: Context-Injected Stream Writer (LangGraph-style)

```python
from typing import AsyncGenerator

async def summarize(text: str, stream: StreamWriter) -> str:
    """Summarize with progress events via injected writer."""
    for i, chunk in enumerate(split_into_chunks(text)):
        partial = await llm.complete(chunk)
        stream.write({"type": "progress", "chunk": i})
    return combine(partials)
```

The `stream: StreamWriter` parameter is auto-detected by name/type and excluded from the tool schema (like ADK's `tool_context` pattern). The return value is the final result.

**Pros**: Clean return type (`-> str`), explicit streaming, magic parameter pattern is well-established
**Cons**: Requires a framework type (`StreamWriter`) -- violates "no Asya imports" principle. Could use `typing.Protocol` to keep it framework-agnostic.

#### Option S4: Dual Return Convention

```python
async def summarize(text: str) -> tuple[str, list[dict]]:
    """Return (final_result, events_emitted_during_processing)."""
    events = []
    for chunk in split_into_chunks(text):
        partial = await llm.complete(chunk)
        events.append({"type": "progress", "partial": partial})
    return combine(partials), events
```

**Pros**: Pure Python, typed, no framework imports
**Cons**: Events are buffered, not streamed -- defeats the purpose. No real-time delivery.

### Recommendation: S1 (Async Generator) + S3 (Stream Writer) Hybrid

Based on the framework research, the most practical approach is:

1. **Simple handlers** stay synchronous: `def f(x: str) -> str`
2. **Async handlers** use `async def`: `async def f(x: str) -> str`
3. **Streaming handlers** use async generators with a convention for the final result:

```python
# Handler mode: typed (auto-detected from signature)
async def summarize(text: str) -> str:
    """Non-streaming async handler."""
    return await llm.complete(text)

# Handler mode: streaming (auto-detected from AsyncGenerator return type)
async def summarize_streaming(text: str) -> AsyncGenerator[dict, None]:
    """Streaming handler -- yields events, last yield with type=result is the final output."""
    for chunk in split_into_chunks(text):
        partial = await llm.complete(chunk)
        yield {"type": "progress", "partial": partial}
    yield {"type": "result", "value": combine(partials)}
```

**Runtime detection hierarchy** (extended from Approach 4):

1. If return type is `AsyncGenerator` → streaming mode (yields routed to SSE channel)
2. If `async def` → async mode (awaited, single response)
3. If typed parameters (not `dict`) → typed mode (extract from payload, return to output key)
4. If `dict -> dict` → current payload/envelope mode

### Streaming Architecture: Dual-Channel

From `asya-bi8-agentic-asya.md`, the proposed dual-channel architecture separates control flow from streaming:

```
Handler yields event
       │
       v
┌─────────────────────┐
│ Runtime classifies   │
│ event type           │
└───┬─────────────┬───┘
    │             │
    v             v
 Control       Streaming
 (SQS/queue)   (HTTP → Gateway → SSE/WebSocket)
    │             │
    v             v
 Next Actor    End User
```

**Event classification** (done by runtime/sidecar, not user code):

| Event Pattern | Channel | Example |
|---------------|---------|---------|
| `{"type": "result", ...}` | Control (queue) | Final handler output → next actor |
| `{"type": "progress", ...}` | Streaming (HTTP) | Progress update → gateway → user |
| `{"type": "tool_call", ...}` | Control (queue) | Tool invocation → tool actor |
| Text delta (partial=True) | Streaming (HTTP) | LLM token → gateway → user |

The handler remains simple -- it just yields dicts. The framework handles classification and routing.

### Impact on Flow DSL

Streaming handlers affect the flow DSL syntax. A flow step that calls a streaming actor needs to declare whether it consumes the stream or passes it through:

```python
# Current flow DSL (synchronous)
def my_flow(p: dict) -> dict:
    p = summarize(p)           # Blocking call
    p = translate(p)           # Blocking call
    return p

# Future: flow with streaming actor
def my_flow(p: dict) -> dict:
    p = summarize(p)           # Actor streams events to gateway
    p = translate(p)           # Receives only the final result
    return p
```

From the flow compiler's perspective, streaming is transparent -- the flow still chains actors sequentially. The streaming events go directly from actor to gateway via the HTTP side-channel; only the final result propagates through the queue to the next actor.

**Open question**: Can an actor in the middle of a flow consume another actor's stream? Or is streaming always actor-to-gateway (end-user facing)?

---

## Handler Mode Summary

After incorporating framework research and streaming design:

| Mode | Signature | Detection | Behavior |
|------|-----------|-----------|----------|
| **payload** (current) | `def f(p: dict) -> dict` | Single dict param | Pass payload, return payload |
| **envelope** (current) | `def f(e: dict) -> dict` | `ASYA_HANDLER_MODE=envelope` | Pass full envelope, return envelope(s) |
| **typed** (proposed) | `def f(city: str) -> str` | Non-dict typed params | Extract from payload by name, store result by output key |
| **async** (proposed) | `async def f(city: str) -> str` | `async def` | Same as typed, but awaited |
| **streaming** (proposed) | `async def f(text: str) -> AsyncGenerator` | `AsyncGenerator` return type | Yield events to stream channel, final result to queue |

### Backward Compatibility

All modes coexist. Detection is automatic based on signature inspection at startup:

```python
import inspect, typing

sig = inspect.signature(handler)
hints = typing.get_type_hints(handler)
return_type = hints.get('return')

if return_type and hasattr(return_type, '__origin__') and return_type.__origin__ is collections.abc.AsyncGenerator:
    mode = "streaming"
elif inspect.iscoroutinefunction(handler):
    mode = "async"
elif all(p.annotation is dict for p in sig.parameters.values()):
    mode = "payload"  # or envelope based on ASYA_HANDLER_MODE
else:
    mode = "typed"
```

---

## Open Questions

1. **Output key naming**: For `def f(x: str) -> str`, which payload field receives the result?
   - Option A: Configured via `outputKey` in AsyncActor CRD (ADK's `output_key` pattern)
   - Option B: Extracted from flow DSL variable assignment (`timezone = detect_timezone(...)`)
   - Option C: Derived from function name (`detect_timezone` → `timezone`? Problematic -- verbs)

2. **Field name mapping**: How to handle payload field names that don't match parameter names?

3. **Streaming protocol**: What's the wire format for streaming events between runtime → sidecar → gateway?
   - Option: Length-prefixed JSON frames (same as current protocol, but multiple per handler invocation)
   - Option: Newline-delimited JSON (NDJSON)

4. **Nested objects**: How to handle complex input types?
   ```python
   def process(user: User) -> Result:  # User is a dataclass/Pydantic model
       ...
   ```

5. **Validation**: Should Asya validate types at runtime? Performance impact?

6. **Stream consumption**: Can an actor in a flow consume another actor's stream? Or is streaming always actor-to-user?

7. **Human-in-the-loop**: How does `suspend`/`resume` interact with typed signatures?
   ```python
   async def approve_expense(amount: float) -> str:
       # How to signal "waiting for human input" here?
       ...
   ```

---

## Champion Framework: Google ADK

Based on the 14-framework survey (`asya-handler-syntax-comparisons.md`), **Google ADK** is the closest architectural match for Asya:

| ADK Concept | Asya Equivalent |
|-------------|-----------------|
| `output_key` (enrichment into shared state) | Payload enrichment pattern |
| Plain functions as tools (no decorator) | "No pip package" principle |
| `SequentialAgent` / `ParallelAgent` / `LoopAgent` | Flow DSL (sequential, fan-out, future loops) |
| `tool_context: ToolContext` (magic parameter) | Proposed stream/context injection |
| `session.state` prefix scoping (`user:`, `app:`, `temp:`) | Potential multi-tenant payload namespacing |
| Event-based async generators | Proposed streaming handler mode |

**Runner-up: LangGraph** for its state reducer concept (typed merge strategies for enrichment) and 5-mode streaming architecture.

---

## Next Steps

1. ~~Survey 5-6 major agentic frameworks for signature patterns~~ ✅ Done (14 frameworks surveyed)
2. Design `outputKey` mechanism (CRD field vs flow inference vs convention)
3. Prototype async handler support in `asya_runtime.py`
4. Design streaming wire protocol (runtime ↔ sidecar ↔ gateway)
5. Prototype runtime introspection for typed handlers
6. Design compatibility layer for @tool decorators
7. Write implementation plan with phased rollout

---

## References

- [Framework comparison survey](asya-handler-syntax-comparisons.md) -- 14 frameworks compared
- [Agentic Asya RFC](asya-bi8-agentic-asya.md) -- Dual-channel streaming architecture
- [ADK Tools Documentation](https://google.github.io/adk-docs/tools/)
- [LangGraph State Management](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Python inspect module](https://docs.python.org/3/library/inspect.html)
- [PEP 484 - Type Hints](https://peps.python.org/pep-0484/)
- [PEP 525 - Asynchronous Generators](https://peps.python.org/pep-0525/)
