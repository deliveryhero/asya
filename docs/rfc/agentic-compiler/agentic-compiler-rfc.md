# RFC: Agentic Flow Compiler

**Status**: Draft
**Author**: Architecture Discussion
**Date**: 2026-02-09
**Related**: asya-handler-signatures.md, asya-bi8-agentic-asya.md, asya-handler-syntax-comparisons.md

---

## Executive Summary

Extend the Asya flow compiler to support **async functions with `await` split points**, enabling compilation of agentic workflows (LLM + tools ReAct loops, sequential/parallel agent pipelines) into distributed stateless actor networks. The core transformation is **Continuation-Passing Style (CPS)**: each `await` in the user's code becomes a message boundary between actors, and local state travels in the payload.

---

## 1. Problem Statement

### What We Have

The current flow compiler handles **synchronous, linear flows**:

```python
def order_processing(p: dict) -> dict:
    p = validate_order(p)
    if p["order_type"] == "express":
        p = express_handler(p)
    else:
        p = standard_handler(p)
    p = payment_processor(p)
    return p
```

Supported constructs:
- ✅ Sequential actor calls: `p = actor(p)`
- ✅ Payload mutations: `p["key"] = value`
- ✅ Conditionals: `if/elif/else`
- ✅ Early returns: `return p`
- ❌ Loops (`for`, `while`)
- ❌ Async/await
- ❌ Generators/yield
- ❌ Free variables across actor boundaries

### What We Need

Agentic workflows require:

```python
async def critic(state: dict) -> AsyncGenerator[dict, None]:
    messages = state.get("messages", [{"role": "user", "content": state["query"]}])

    while True:
        response = await llm_call(messages, model="gemini-2.5-flash")

        if response.tool_calls:
            for tc in response.tool_calls:
                result = await google_search(**tc.args)
                messages.append({"role": "tool", "content": result, "tool_call_id": tc.id})
        else:
            yield {"type": "result", "critique": response.text, "messages": messages}
            return
```

This is the **ReAct loop pattern** -- the most common agentic workflow. The compiler must:
1. Split at each `await` into separate actors
2. Generate loop-back routers for `while True`
3. Classify `yield` events as streaming vs control
4. Ensure all state travels in payload (no sticky sessions)

---

## 2. Design Principles

### 2.1 CPS Transformation

**Core idea**: Each `await` in the user's async function becomes a continuation boundary. The compiler transforms:

```python
x = await A(state)
y = await B(x)
return y
```

Into a network of actors and routers:

```
[Router-1: prepare state, route to A]
    -> [Actor A: process, return result]
        -> [Router-2: receive A's result, route to B]
            -> [Actor B: process, return result]
                -> [Router-3: receive B's result, return]
```

Each router is a generated envelope-mode handler that manipulates `route.actors` to insert the next steps.

### 2.2 State in Payload

All state travels in the envelope payload. No sticky sessions, no external state store (for sequential flows). Any pod can process any message.

```json
{
  "id": "env-123",
  "route": {"actors": ["dispatch-router", "llm-call", "..."], "current": 1},
  "payload": {
    "query": "What is the capital of France?",
    "messages": [
      {"role": "user", "content": "What is the capital of France?"},
      {"role": "assistant", "tool_calls": [{"name": "search", "args": {}}]},
      {"role": "tool", "content": "Paris is the capital...", "tool_call_id": "tc1"}
    ]
  }
}
```

### 2.3 Free Variables (Future)

Local variables that cross `await` boundaries are **not supported initially**. The compiler will emit an error if a local variable is assigned before an `await` and used after it:

```python
async def flow(state: dict) -> dict:
    var1 = compute_something()        # local variable
    state = await actor_a(state)      # await split
    print(var1)                       # ERROR: var1 crosses await boundary
    return state
```

**Rationale**: The user must explicitly pass all state through `state` (the payload dict). This keeps the system simple and stateless.

**Future vision**: The compiler could auto-serialize free variables into the payload before an `await` and restore them after. This requires:
- Static analysis to detect which variables are live across boundaries
- Automatic save: `state["__local_var1"] = var1` before split
- Automatic restore: `var1 = state.pop("__local_var1")` after split
- Tightly coupled to the typed signatures problem (deferred)

### 2.4 Payload Mode Only (For Now)

All actors receive and return `dict` (or TypedDict/Pydantic). The typed handler signatures (`def get_weather(city: str) -> str`) are a separate, future concern. This RFC focuses on control flow compilation.

---

## 3. New IR Node Types

Extending `src/asya-cli/asya_cli/flow/ir.py`:

```python
# Existing nodes (unchanged):
# ActorCall(name: str)
# Mutation(code: str)
# Condition(test: str, true_branch, false_branch)
# Convergence(label: str)
# Return()

# New nodes:

@dataclass
class AwaitCall(IROperation):
    """An awaited actor call: state = await actor(state)

    This is the primary CPS split point. The compiler generates a
    continuation router at each AwaitCall boundary.
    """
    name: str           # Actor/function name (e.g., "llm_call", "google_search")
    assign_to: str      # Variable receiving result (e.g., "state", "response")

@dataclass
class WhileLoop(IROperation):
    """A while loop: while condition: body

    The compiler generates a back-edge router that re-routes to the
    loop start after each iteration. The condition is checked by a
    conditional router.
    """
    condition: str      # Python expression (e.g., "True", "not state.get('done')")
    body: list          # List of IROperation nodes

@dataclass
class YieldEvent(IROperation):
    """A yield expression inside an async generator.

    Yields are classified as:
    - streaming: intermediate events (text deltas, progress) -> HTTP side-channel
    - control: last yield with type="result" -> queue -> next actor
    """
    code: str           # The yielded expression source code
    is_final: bool      # True if this is the last yield before return

@dataclass
class AsyncFlowFunction(IROperation):
    """Marker for async flow function signature.

    Tracks whether the flow is:
    - async def f(state: dict) -> dict          (async, single response)
    - async def f(state: dict) -> AsyncGenerator (async generator, streaming)
    """
    is_generator: bool  # True if return type is AsyncGenerator
```

---

## 4. Parser Extensions

### 4.1 Async Flow Function Detection

Current parser finds: `def flow_name(p: dict) -> dict`

New parser also accepts:
- `async def flow_name(state: dict) -> dict`
- `async def flow_name(state: dict) -> AsyncGenerator[dict, None]`

Parameter name extended from `p`/`payload` to also accept `state`/`s`.

```python
# parser.py: _find_flow_function()
# Accept both sync and async function definitions
if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
    # Check parameter: must be single param typed as dict
    # Check return type: dict or AsyncGenerator[dict, None]
```

### 4.2 Await Expression Parsing

New `_parse_await()` method:

```python
# Recognizes:
# state = await actor(state)         -> AwaitCall(name="actor", assign_to="state")
# response = await llm_call(state)   -> AwaitCall(name="llm_call", assign_to="response")
# await fire_and_forget(state)       -> AwaitCall(name="fire_and_forget", assign_to=None)
```

Key rules:
- The awaited call must be a function/method call (not arbitrary expressions)
- The argument must be `state`/`p`/`payload` (the flow parameter)
- Assignment target is tracked for the continuation router

### 4.3 While Loop Parsing

New `_parse_while()` method:

```python
# Recognizes:
# while True:                        -> WhileLoop(condition="True", body=[...])
# while not state.get("done"):       -> WhileLoop(condition="not state.get('done')", body=[...])
```

Key rules:
- Body is parsed recursively (can contain AwaitCall, Condition, Mutation, etc.)
- `break` maps to a conditional `Return` (exit the loop)
- `continue` maps to a jump back to loop start

### 4.4 Yield Expression Parsing

New `_parse_yield()` method:

```python
# Recognizes:
# yield {"type": "progress", ...}    -> YieldEvent(code='...', is_final=False)
# yield {"type": "result", ...}      -> YieldEvent(code='...', is_final=True)
```

Key rules:
- `is_final` is determined by static analysis: if the yield is followed by `return`, it's final
- Inside `while True`, the yield before `return` in the else branch is final
- Intermediate yields are streaming events routed to HTTP gateway

---

## 5. Grouper: CPS Transformation

The grouper (`grouper.py`) receives IR operations and produces routers. The CPS transformation is the core new capability.

### 5.1 Await Split Algorithm

For each `AwaitCall`, the grouper:

1. **Terminates the current router** -- any accumulated mutations become the current router's body
2. **Creates an actor reference** -- the awaited function becomes an actor in the route
3. **Creates a continuation router** -- receives the actor's result, continues with the next operations

**Example**:

```python
# Input IR:
[
    Mutation("messages = state.get('messages', [])"),
    AwaitCall(name="llm_call", assign_to="response"),
    Condition(test="response.tool_calls", ...),
]

# Output Routers:
Router("entry", mutations=["messages = state.get('messages', [])"], next=["llm_call"])
Router("dispatch", condition=Condition("response.tool_calls", ...), ...)
```

### 5.2 Continuation Passing

When an `AwaitCall` assigns to a variable other than `state`:

```python
response = await llm_call(state)
```

The continuation router must extract the actor's return value from the payload and make it available under the name `response` for subsequent operations. Two strategies:

**Strategy A: Output key convention** -- The actor writes its result to `payload["__return__"]`, and the continuation router extracts it:

```python
# Generated continuation router:
def continuation_router(envelope):
    p = envelope["payload"]
    response = p.pop("__return__")  # Extract actor result
    # ... continue with 'response' variable
```

**Strategy B: Whole-payload convention** -- The actor's entire return dict IS the updated payload. The continuation router accesses fields directly. This is simpler and matches current behavior.

**Decision**: Strategy B (whole-payload) for now. The `assign_to` variable in AwaitCall is used only for code generation in the continuation router -- it's a local alias for the payload.

### 5.3 Loop Router Generation

For `WhileLoop`, the grouper generates:

1. **Loop-condition router** -- Checks the condition, routes to loop body or exit
2. **Loop body** -- Compiled normally (may contain AwaitCalls, creating sub-routers)
3. **Loop-back router** -- After the last operation in the body, routes back to the loop-condition router

```
                +-------------------------+
                v                         |
    [loop-condition-router]               |
        |              |                  |
     (true)         (false)               |
        |              |                  |
        v              v                  |
    [loop-body]   [exit/next]             |
        |                                 |
        v                                 |
    [loop-back-router] -------------------+
```

For `while True`, the condition router is optimized away (always enters loop body).

### 5.4 Yield Event Handling

Yield nodes don't create routers. Instead:
- Intermediate yields are compiled as streaming event emissions (handled by runtime/sidecar)
- The final yield is treated as the actor's return value

In the generated router code:
- Intermediate yields -> sidecar HTTP side-channel
- Final yield -> sidecar queue channel (to next actor)

---

## 6. Code Generator Extensions

### 6.1 Continuation Router Code

Generated code for a continuation router after an `AwaitCall`:

```python
def continuation_after_llm_call(envelope: dict) -> dict:
    """Auto-generated continuation router.

    Receives result from 'llm_call' actor, dispatches based on tool_calls.
    """
    p = envelope['payload']
    r = envelope['route']
    c = r['current']

    # Continuation logic (from user's source code)
    if p.get('tool_calls'):
        _next = [resolve('google_search')]
        # After google_search, route to collect router
        _next.append(resolve('collect_after_search'))
    else:
        _next = []  # No more actors, flow ends

    r['actors'][c+1:c+1] = _next
    r['current'] = c + 1
    return envelope
```

### 6.2 Loop Router Code

Generated code for a loop-back router:

```python
def loop_back_to_llm_call(envelope: dict) -> dict:
    """Auto-generated loop router.

    Appends tool result to messages, routes back to llm_call.
    """
    p = envelope['payload']
    r = envelope['route']
    c = r['current']

    # Mutations from user code
    p['messages'].append({
        'role': 'tool',
        'content': p.get('__tool_result__'),
        'tool_call_id': p.get('__tool_call_id__')
    })

    # Route back to loop start
    _next = [resolve('llm_call'), resolve('dispatch_after_llm_call')]
    r['actors'][c+1:c+1] = _next
    r['current'] = c + 1
    return envelope
```

### 6.3 Streaming Event Code

Streaming is handled by the runtime and sidecar, not by generated router code. Routers only see the final result from each actor.

```python
# Generated documentation in routers.py header:
# NOTE: Actors 'llm_call' and 'reviser' are streaming actors.
# They yield intermediate events to the HTTP side-channel.
# The sidecar handles event classification and routing.
# No special router code needed -- streaming is transparent to routers.
```

---

## 7. Validated Example: ADK LLM Auditor

### 7.1 Real ADK Code

From `adk-samples/llm-auditor`:

```python
# ADK declarative:
from google.adk.agents import SequentialAgent

critic_agent = Agent(
    model="gemini-2.5-flash",
    tools=[google_search],
    instruction="Evaluate the answer, verify accuracy using search...",
    after_model_callback=_render_reference,
)

reviser_agent = Agent(
    model="gemini-2.5-flash",
    instruction="Revise the answer based on the critique...",
    after_model_callback=_remove_end_of_edit_mark,
)

llm_auditor = SequentialAgent(
    name="llm_auditor",
    sub_agents=[critic_agent, reviser_agent],
)
```

### 7.2 Equivalent Asya Async Flow

```python
from typing import AsyncGenerator

# Top-level flow: sequential composition
async def llm_auditor(state: dict) -> dict:
    state = await critic(state)     # await split #1 (expands to ReAct sub-flow)
    state = await reviser(state)    # await split #2 (single LLM call)
    return state

# Sub-flow: ReAct loop for critic agent
async def critic(state: dict) -> AsyncGenerator[dict, None]:
    state["messages"] = state.get("messages", [{"role": "user", "content": state["query"]}])

    while True:
        state = await llm_call(state)  # Split: call LLM actor

        if state.get("tool_calls"):
            state = await google_search(state)  # Split: call tool actor
            state["messages"].append({
                "role": "tool",
                "content": state["search_result"],
                "tool_call_id": state["tool_calls"][0]["id"],
            })
        else:
            state["critique"] = state["llm_response"]
            yield {"type": "result", **state}  # Control event -> next actor
            return

# Simple handler: single LLM call (no tools)
async def reviser(state: dict) -> dict:
    state = await llm_call(state)
    state["revised_answer"] = state.pop("llm_response")
    return state
```

### 7.3 Compiled Actor Network

```
                     +----------------------------------------------+
                     |              LLM AUDITOR FLOW                |
                     |                                              |
 +-------------+    |  +----------+    +------------------+       |
 | entry-router |-->|  | llm-call |--->| dispatch-router  |       |
 +-------------+    |  +----------+    +---+----------+---+       |
                     |                      |          |            |
                     |          tool_calls  |          |  no tools  |
                     |                      v          |            |
                     |             +--------------+    |            |
                     |             |google-search |    |            |
                     |             +------+-------+    |            |
                     |                    |            |            |
                     |                    v            |            |
                     |            +--------------+     |            |
                     |            |collect-router|     |            |
                     |            +------+-------+     |            |
                     |                   |             |            |
                     |         +---------+             |            |
                     |         |(loop back)            |            |
                     |         v                       v            |
                     |    [llm-call]             +----------+       |
                     |                          | reviser  |       |
                     |                          | llm-call |       |
                     |                          +-----+----+       |
                     |                                |            |
                     +--------------------------------+------------+
                                                      |
                                                      v
                                                 (happy-end)
```

### 7.4 Actors Deployed

| Actor | Type | Handler | Description |
|-------|------|---------|-------------|
| `entry-router` | Generated | `routers.entry_llm_auditor` | Initializes messages, routes to `llm-call` |
| `llm-call` | User-provided | `llm_handlers.call_gemini` | Calls Gemini API with messages + tools |
| `dispatch-router` | Generated | `routers.dispatch_after_llm_call` | Checks tool_calls, routes to search or reviser |
| `google-search` | User-provided | `tools.google_search` | Executes Google Search API |
| `collect-router` | Generated | `routers.collect_after_search` | Appends tool result to messages, loops back |
| `reviser-llm-call` | User-provided | `llm_handlers.call_gemini_revise` | Calls Gemini for revision |

### 7.5 Execution Trace

1. **entry-router** (pod any): `{"query": "..."}` -> add messages -> route to `llm-call`
2. **llm-call** (pod #37): Call Gemini -> returns `{"tool_calls": [{"name": "search", ...}]}`
3. **dispatch-router** (pod any): See tool_calls -> route to `google-search`
4. **google-search** (pod #12): Execute search -> returns `{"result": "Paris is..."}`
5. **collect-router** (pod any): Append tool result to messages -> route to `llm-call`
6. **llm-call** (pod #85, different!): Call Gemini -> returns `{"text": "Paris...", "tool_calls": []}`
7. **dispatch-router** (pod any): No tool_calls -> route to `reviser-llm-call`
8. **reviser-llm-call** (pod #3): Call Gemini -> returns revised answer
9. -> `happy-end`

Every actor is **stateless**. Full conversation state travels in payload. No sticky sessions.

---

## 8. Compilation Levels

The compiler handles two distinct levels:

### Level 1: Orchestration Compilation (Existing + Extended)

Translating sequential/conditional/parallel agent composition into route configurations.

```python
# ADK equivalent: SequentialAgent(sub_agents=[critic, reviser])
async def llm_auditor(state: dict) -> dict:
    state = await critic(state)
    state = await reviser(state)
    return state
```

Compiled: linear route `[critic, reviser]` -- this is what the current flow compiler already does (with `p = actor(p)` syntax), extended for `await`.

### Level 2: Agent Decomposition (New)

Translating an LLM agent's internal ReAct loop into a router network.

```python
# ADK equivalent: Agent(model="gemini", tools=[google_search])
async def critic(state: dict) -> AsyncGenerator[dict, None]:
    while True:
        state = await llm_call(state)
        if state.get("tool_calls"):
            state = await google_search(state)
            # ... append to messages ...
        else:
            yield {"type": "result", **state}
            return
```

Compiled: `llm-call -> dispatch-router -> [tools] -> collect-router -> (loop back)` -- this is **new**.

### Level 3: Framework Translation (Future)

Recognizing ADK/LangGraph/etc declarative syntax and compiling it:

```python
# Future: compiler understands ADK declarations
from google.adk.agents import SequentialAgent, Agent

auditor = SequentialAgent(
    sub_agents=[
        Agent(model="gemini", tools=[search], instruction="critique..."),
        Agent(model="gemini", instruction="revise..."),
    ]
)
# -> Compiler generates the full actor network
```

This RFC covers **Levels 1 and 2**. Level 3 is future work.

---

## 9. Testing Strategy

### 9.1 Test Principles

- **Realistic examples**: All test flows based on real ADK samples, not synthetic code
- **Compilation tests**: Verify AST parsing, IR generation, router generation, code generation
- **Execution tests**: Execute generated routers against mock envelopes, verify route manipulation
- **No infrastructure tests** in the compiler itself -- infrastructure tests live in `testing/component/flow-compiler/`

### 9.2 Reference Test Cases

#### Test Case 1: Sequential Async Flow

Based on ADK LLM Auditor (SequentialAgent with 2 sub-agents):

```python
# test fixture: examples/flows/async_sequential.py
async def llm_auditor(state: dict) -> dict:
    state = await critic(state)
    state = await reviser(state)
    return state
```

Expected compilation:
- 3 routers: entry, continuation-after-critic, end
- Route: `[entry, critic, continuation, reviser, end]`

#### Test Case 2: ReAct Loop (LLM + Tools)

Based on ADK LlmAgent with tools (the core agentic pattern):

```python
# test fixture: examples/flows/react_loop.py
async def agent_with_tools(state: dict) -> AsyncGenerator[dict, None]:
    state["messages"] = state.get("messages", [])

    while True:
        state = await llm_call(state)

        if state.get("tool_calls"):
            state = await execute_tool(state)
        else:
            yield {"type": "result", **state}
            return
```

Expected compilation:
- 4+ routers: entry, dispatch, collect (loop-back), end-yield
- Loop back-edge from collect-router to llm-call
- Conditional branch in dispatch-router

#### Test Case 3: Conditional Async

Based on ADK agents with conditional routing:

```python
# test fixture: examples/flows/async_conditional.py
async def content_pipeline(state: dict) -> dict:
    state = await classifier(state)

    if state["content_type"] == "text":
        state = await text_processor(state)
    elif state["content_type"] == "image":
        state = await image_processor(state)
    else:
        state = await generic_processor(state)

    state = await quality_check(state)
    return state
```

Expected compilation:
- Entry router + conditional router + convergence + end
- Three branches, all converging to quality_check

#### Test Case 4: Nested Await in Conditional

```python
# test fixture: examples/flows/async_nested.py
async def review_pipeline(state: dict) -> dict:
    state = await initial_review(state)

    if state["score"] < 0.5:
        state = await detailed_review(state)
        state = await human_review(state)
    else:
        state = await auto_approve(state)

    return state
```

Expected: proper continuation routers preserving conditional structure.

#### Test Case 5: Multi-Tool ReAct

Based on ADK agents with multiple tools:

```python
# test fixture: examples/flows/react_multi_tool.py
async def research_agent(state: dict) -> AsyncGenerator[dict, None]:
    state["messages"] = state.get("messages", [])

    while True:
        state = await llm_call(state)

        if state.get("tool_calls"):
            tool_name = state["tool_calls"][0]["name"]
            if tool_name == "search":
                state = await web_search(state)
            elif tool_name == "calculator":
                state = await calculator(state)
            elif tool_name == "code_exec":
                state = await code_executor(state)
        else:
            yield {"type": "result", **state}
            return
```

Expected: dispatch router with multi-branch tool routing + loop back-edge.

### 9.3 Test Structure

```
testing/component/flow-compiler/
  tests/
    test_async_parser.py        # Async flow parsing
    test_await_splitting.py     # CPS transformation
    test_loop_compilation.py    # While loop -> back-edge routers
    test_yield_handling.py      # Yield event classification
    test_react_loop.py          # Full ReAct loop compilation + execution
    test_adk_llm_auditor.py     # Real ADK example validation
    test_free_variables.py      # Free variable detection (errors)
examples/flows/
    async_sequential.py         # Simple sequential async flow
    react_loop.py               # ReAct loop pattern
    react_multi_tool.py         # ReAct with multiple tools
    async_conditional.py        # Conditional with await
    async_nested.py             # Nested await in branches
    compiled/                   # Expected compilation output (golden files)
```

---

## 10. Runtime Support

### 10.1 Async Handler Execution

The runtime (`asya_runtime.py`) must support `async def` handlers:

```python
# Current (synchronous):
result = handler(payload)

# New (async):
import asyncio
if asyncio.iscoroutinefunction(handler):
    result = asyncio.run(handler(payload))
else:
    result = handler(payload)
```

### 10.2 AsyncGenerator Handler Support

For streaming handlers, the runtime iterates the generator:

```python
if inspect.isasyncgenfunction(handler):
    last_event = None
    async for event in handler(payload):
        if is_streaming_event(event):
            send_to_streaming_channel(event)  # HTTP -> gateway
        last_event = event
    result = last_event  # Last yield = control event -> queue
else:
    result = handler(payload)
```

### 10.3 Streaming Protocol (Runtime <-> Sidecar)

Current protocol: single JSON frame per handler invocation.

New protocol: multiple frames per invocation for streaming handlers:

```
Frame 1: {"type": "stream", "data": {"type": "text_delta", "delta": "The "}}
Frame 2: {"type": "stream", "data": {"type": "text_delta", "delta": "capital"}}
Frame 3: {"type": "stream", "data": {"type": "text_delta", "delta": " is..."}}
Frame 4: {"type": "result", "data": {"text": "The capital is Paris", "messages": [...]}}
```

The sidecar:
- `type: "stream"` -> HTTP POST to gateway with `envelope_id` for correlation
- `type: "result"` -> normal envelope routing to next actor in queue

---

## 11. Sidecar Extensions

### 11.1 Multi-Frame Protocol

Extend the Unix socket protocol to support multiple response frames:

```go
// Current: read one frame, route to next queue
frame := readFrame(conn)
routeToNextActor(frame)

// New: read frames until "result" frame
for {
    frame := readFrame(conn)
    switch frame.Type {
    case "stream":
        forwardToGateway(frame.Data, envelopeID)  // HTTP side-channel
    case "result":
        routeToNextActor(frame.Data)  // Queue routing
        return
    }
}
```

### 11.2 HTTP Streaming Route

The sidecar forwards streaming events to the gateway via HTTP:

```
POST /api/v1/envelopes/{envelope_id}/events
Content-Type: application/json

{"type": "text_delta", "delta": "The capital", "timestamp": "..."}
```

The gateway then pushes these to connected SSE/WebSocket clients.

---

## 12. Compiler Pipeline Summary

```
                      User's async flow (.py)
                              |
                              v
                    +------------------+
                    |  Parser (AST)    |  Detect: async def, await, while, yield
                    +--------+---------+
                             |
                             v
                    +------------------+
                    |  IR Operations   |  AwaitCall, WhileLoop, YieldEvent, ...
                    +--------+---------+
                             |
                             v
                    +------------------+
                    |    Grouper       |  CPS transform: split at await boundaries
                    |  (CPS Engine)    |  Loop transform: generate back-edges
                    +--------+---------+
                             |
                             v
                    +------------------+
                    |  Router Graph    |  Entry, continuation, dispatch, collect, end
                    +--------+---------+
                             |
                     +-------+-------+
                     v               v
            +---------------+  +---------------+
            |  CodeGen      |  |  DotGen       |
            |  (routers.py) |  |  (flow.dot)   |
            +---------------+  +---------------+
```

---

## 13. Scope and Phasing

### Phase 1: Parser Extensions (Foundation)
- IR: New node types (AwaitCall, WhileLoop, YieldEvent, AsyncFlowFunction)
- Parser: `async def` detection
- Parser: `await` expression recognition
- Parser: `while` loop recognition
- Parser: `yield` expression recognition
- **Test**: Parsing test cases, verify IR output

### Phase 2: CPS Transformation (Core)
- Grouper: CPS split at await boundaries -> continuation routers
- Grouper: Loop back-edge generation for while loops
- CodeGen: Continuation router code generation
- CodeGen: Loop router code generation
- **Test**: Compilation of all reference test cases, execution against mock envelopes

### Phase 3: Streaming Support
- CodeGen: Streaming event classification
- Runtime: Async handler execution (`asyncio.run`)
- Runtime: AsyncGenerator multi-frame response
- Sidecar: Multi-frame protocol extension
- Sidecar: HTTP streaming forwarding to gateway
- **Test**: Streaming event routing tests

### Phase 4: Integration and Validation
- Full ADK LLM Auditor example: compile + deploy + test
- ReAct loop with real tool actors
- Component tests with mock LLM and tool actors
- Documentation and examples

### Future (Out of Scope)
- Free variable analysis and auto-serialization
- ADK declarative syntax recognition (Level 3 compilation)
- Typed handler signatures (`def get_weather(city: str) -> str`)
- Parallel await (`asyncio.gather` equivalent)
- Try-catch error routing

---

## 14. Open Questions

1. **`for` loop handling**: Should `for tc in response.tool_calls` be unrolled or handled as a loop? For now, we assume single tool call per iteration (the router dispatches to one tool at a time).

2. **Multiple tool calls per LLM response**: LLMs can return multiple tool calls. Should the dispatch router:
   - (A) Process them sequentially (simpler, one at a time)?
   - (B) Fan-out to parallel tool actors (requires fan-in aggregation)?
   Decision deferred. Start with (A).

3. **Payload growth**: Messages array grows with each loop iteration. Need payload size monitoring and eventual compression (reference: asya-bi8 session state strategy -- binary protocol, artifact offloading).

4. **Loop termination**: What happens if the LLM never stops calling tools? Need `max_iterations` equivalent. The `while True` loop should have a compiler-enforced or runtime-enforced iteration limit.

5. **Error in tool actor**: If a tool actor fails, should the loop retry, break, or route to error-end? Currently, errors always go to error-end. Should the dispatch router support error recovery?

---

## 15. References

- [Flow Compiler Source](../../../src/asya-cli/asya_cli/flow/) -- Current compiler implementation
- [Handler Signatures RFC](../asya-handler-signatures.md) -- Typed signatures design
- [Framework Comparison](../asya-handler-syntax-comparisons.md) -- 14-framework survey
- [Agentic Asya RFC](../asya-bi8-agentic-asya.md) -- Dual-channel streaming architecture
- [ADK Sequential Agent](https://github.com/google/adk-python/blob/main/src/google/adk/agents/sequential_agent.py)
- [ADK LLM Auditor Sample](https://github.com/google/adk-samples/tree/main/python/agents/llm-auditor)
- [ADK BaseLlmFlow](https://github.com/google/adk-python/blob/main/src/google/adk/flows/llm_flows/base_llm_flow.py)
- [PEP 525 -- Asynchronous Generators](https://peps.python.org/pep-0525/)
