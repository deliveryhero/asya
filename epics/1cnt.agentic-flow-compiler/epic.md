---
title: "Agentic Flow Compiler"
priority: 1 # high
type: epic
---


Extend the Asya flow compiler to support async functions with await split points, enabling compilation of agentic workflows (LLM + tools ReAct loops, sequential/parallel agent pipelines) into distributed stateless actor networks.

## Core Transformation: CPS (Continuation-Passing Style)

Each `await` in the user's async function becomes a message boundary between actors. The compiler splits the function at await points, generating continuation routers that carry state forward in the payload.

## Scope

### Level 1: Orchestration Compilation (extend existing)
- `async def flow(state: dict) -> dict` with `state = await actor(state)` calls
- Compiles to linear/conditional actor routes (extends current sync compiler)

### Level 2: Agent Decomposition (new)
- `async def agent(state: dict) -> AsyncGenerator[dict, None]` with ReAct loops
- `while True` + `await llm_call` + conditional tool dispatch + `yield` streaming
- Compiles to: llm-call -> dispatch-router -> [tools] -> collect-router -> (loop back)

### Level 3: Framework Translation (future, out of scope)
- Recognize ADK SequentialAgent/ParallelAgent declarations and compile

## Phases

1. **Parser Extensions**: New IR nodes, async def/await/while/yield parsing
2. **CPS Transformation**: Grouper splits at await, generates continuation/loop routers
3. **Streaming Support**: Runtime async execution, multi-frame sidecar protocol
4. **Integration**: ADK LLM Auditor reference example, ReAct loop tests

## Validated Example

Real ADK LLM Auditor (SequentialAgent with critic+reviser) compiled to stateless actor network. See docs/rfc/agentic-compiler/agentic-compiler-rfc.md for full design.

## Key Design Decisions

- **Payload mode only** (for now): All actors receive/return dict
- **Free variables**: Not supported across await boundaries (user must pass state explicitly)
- **Last yield = control event**: AsyncGenerator last yield goes to queue, intermediates go to HTTP streaming
- **No sticky sessions**: Full state travels in payload, any pod can process any message

## RFC: Agentic Flow Compiler

### Executive Summary

Extend the Asya flow compiler to support **async functions with `await` split points**, enabling compilation of agentic workflows (LLM + tools ReAct loops, sequential/parallel agent pipelines) into distributed stateless actor networks. The core transformation is **Continuation-Passing Style (CPS)**: each `await` in the user's code becomes a message boundary between actors, and local state travels in the payload.

---

### 1. Problem Statement

#### What We Have

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
- ✅ Loops (`for`, `while`)
- ✅ Generators/yield
- ✅ Async/await
- ❌ `async for` and `yield` (for partial and full events)
- ❌ Free variables across actor boundaries

#### What We Need

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
3. Support streaming event composition across nested flows
4. Ensure all state travels in payload (no sticky sessions)

---

### 2. Design Principles

#### 2.1 CPS Transformation

**Core idea**: Each `await` in the user's async function becomes a continuation boundary. The compiler transforms:

```python
state = await A(state)
state = await B(state)
return state
```

Into a network of actors and routers:

```
[Router-1: prepare state, route to A]
    -> [Actor A: process, return result, route to B]
        -> [Actor B: process, return result]
            -> [Router-3: receive B's result, return]
```

Each router is a generated envelope-mode handler that manipulates `route.actors` to insert the next steps.

#### 2.2 State in Payload

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

#### 2.3 Free Variables (Future)

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

#### 2.4 Payload Mode Only (For Now)

All actors receive and return `dict` (or TypedDict/Pydantic). The typed handler signatures (`def get_weather(city: str) -> str`) are a separate, future concern. This RFC focuses on control flow compilation.

#### 2.5 Streaming Event Composition

**Problem**: In the current asya design, streaming (non-end) events from any actor are sent directly to asya-gateway via HTTP, bypassing intermediate actors. This makes flow composition of streaming events impossible — a parent flow cannot intercept, transform, or filter events yielded by a child flow.

**Solution**: Events follow the ADK Event model with a `partial` field that determines routing:

- **`partial=True`**: Streaming/display events (text deltas, progress - results to be routed backwards, back to the http handler). Routed via `ASYA_PARTIAL_EVENTS_ROUTE`.
- **`partial=False`**: Control events (results to be routed forward, down the route). Routed via `route.actors` to the next actor in the pipeline.

Each actor may have a compiler-set environment variable **`ASYA_PARTIAL_EVENTS_ROUTE`** (default to "") that controls where partial events go:

| Value | Meaning | When |
|-------|---------|------|
| `""` (empty, default) | HTTP direct to gateway | No parent transforms partial events |
| `"mutation-router-xyz"` | Queue to mutation router | Parent flow transforms partial events |

**Dual routing paths**:

```
                    yield event
                        |
                  partial field?
                   /         \
              partial=True    partial=False
                  |               |
       ASYA_PARTIAL_EVENTS_ROUTE  route.actors[current+1]
           /           \              |
        empty        non-empty        v
          |              |        next actor
          v              v        (or happy-end)
       gateway  ASYA_PARTIAL_EVENTS_ROUTE[0]
                        |
                        v
                ASYA_PARTIAL_EVENTS_ROUTE[1]
                        |
                        v
                   (re-enters routing)
```

**Terminal behavior** (route exhausted):
- `partial=True` + route exhausted -> forward to gateway (streaming display)
- `partial=False` + route exhausted -> forward to `happy-end` (normal completion)

**Compiler optimization**: The compiler statically analyzes each `async for event in sub_flow(p): ... yield event` body:

- **Identity yield** (no code between `async for` and `yield`, or only non-await local operations): set `ASYA_PARTIAL_EVENTS_ROUTE=""` -> events stream directly to gateway with zero added latency
- **Mutation yield** (any transformation, await, or conditional in the yield body): generate a mutation router actor, set `ASYA_PARTIAL_EVENTS_ROUTE="<generated-router-name>"` -> events pass through the router for processing

This preserves ADK-like composability while optimizing the common identity-passthrough case to match direct-to-gateway performance.

---

### 3. New IR Node Types

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

    Each yield produces an event that becomes the payload of a new message.
    The event follows the ADK Event schema with a 'partial' field:
    - partial=True  -> routed via ASYA_PARTIAL_EVENTS_ROUTE (streaming)
    - partial=False -> routed via route.actors (control flow)

    The compiler does NOT classify yields as streaming vs control —
    that distinction is made at runtime based on the event's partial field.
    """
    code: str           # The yielded expression source code

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

### 4. Parser Extensions

#### 4.1 Async Flow Function Detection

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

#### 4.2 Await Expression Parsing

New `_parse_await()` method:

```python
# Recognizes:
# state = await actor(state)         -> AwaitCall(name="actor", assign_to="state")
# response = await llm_call(state)   -> AwaitCall(name="llm_call", assign_to="response")
# await fire_and_forget(state)       -> COMPILER ERROR (unsupported)
```

Key rules:
- The awaited call must be a function/method call (not arbitrary expressions)
- The argument must be `state`/`p`/`payload` (the flow parameter)
- Assignment target is tracked for the continuation router
- Fire-and-forget `await` (no assignment) is not supported — the compiler emits an error

#### 4.3 While Loop Parsing

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

#### 4.4 Yield Expression Parsing

New `_parse_yield()` method:

```python
# Recognizes:
# yield event                        -> YieldEvent(code='event')
# yield {"partial": True, ...}       -> YieldEvent(code='{"partial": True, ...}')
# yield p                            -> YieldEvent(code='p')
```

Key rules:
- The compiler does **not** classify yields as streaming vs control — no `is_final` analysis
- The yielded expression becomes the payload of a new message at runtime
- The `partial` field in the yielded event is a **runtime concern**, not a compile-time one
- Multiple yields = fan-out (each yield produces an independent message)

#### 4.5 CPS Split Annotation

The `# asya: no-split` annotation prevents CPS splitting at an `await`:

```python
async def flow(p: dict):
    # to run await call in-process, no actor boundary
    result = await some_local_helper(p)  # asya: no-split
    yield result
```

Key rules:
- Annotation must appear on the line immediately preceding the `await`
- The annotated `await` runs in the same actor process (no message boundary)
- Use for lightweight local helpers that don't need actor isolation

---

### 5. Grouper: CPS Transformation

The grouper (`grouper.py`) receives IR operations and produces routers. The CPS transformation is the core new capability.

#### 5.1 Await Split Algorithm

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

#### 5.2 Continuation Passing

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

#### 5.3 Loop Router Generation

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

#### 5.4 Yield Event Handling and Streaming Composition

Yield events in async generators follow CPS semantics. The compiler analyzes `async for ... yield` patterns to determine whether streaming events need transformation.

##### 5.4.1 CPS for Async Generator Iteration

When a flow iterates over a sub-flow's events:

```python
async def parent_flow(p: dict):
    async for event in child_flow(p):
        event["annotated"] = True   # transformation
        yield event
```

The compiler splits this into:
1. **Actor call**: `child_flow` becomes an actor that yields events
2. **Mutation router**: Generated router that applies `event["annotated"] = True` to each event from `child_flow`
3. **ASYA_PARTIAL_EVENTS_ROUTE**: Set on `child_flow`'s actor to route partial events through the mutation router

##### 5.4.2 Identity Yield Optimization

The compiler performs static analysis on the yield body (the code between `async for event` and `yield event`):

**Identity yield** — no transformation needed:
```python
# Case 1: bare passthrough
async for event in child_flow(p):
    yield event

# Case 2: only non-await local operations (comments, logging)
async for event in child_flow(p):
    # just passing through
    yield event
```

**Optimization**: Set `ASYA_PARTIAL_EVENTS_ROUTE=""` on the child actor. Events stream directly to gateway (or the parent's own partial route), skipping the mutation router entirely.

**Mutation yield** — transformation required:
```python
# Case 1: payload mutation
async for event in child_flow(p):
    event["source"] = "parent"
    yield event

# Case 2: await in yield body
async for event in child_flow(p):
    event = await enrich(event)
    yield event

# Case 3: conditional in yield body
async for event in child_flow(p):
    if event.get("important"):
        yield event
```

**Action**: Generate a mutation router actor. Set `ASYA_PARTIAL_EVENTS_ROUTE="<mutation-router-name>"` on the child actor.

##### 5.4.3 Mutation Router Generation

For non-identity yield bodies, the compiler generates a lightweight router:

```python
# Generated mutation router for parent_flow's yield body
def parent_flow_yield_router(envelope: dict) -> dict:
    event = envelope['payload']

    # User's yield body code (transformed)
    event["annotated"] = True

    return envelope  # payload modified in-place
```

The same mutation router handles both `partial=True` and `partial=False` events — the transformation is the same regardless of the event's partial flag. After processing, the sidecar routes the event based on its `partial` field:
- `partial=True` -> next `ASYA_PARTIAL_EVENTS_ROUTE` (or gateway if empty)
- `partial=False` -> next actor in `route.actors` (or `happy-end` if exhausted)

##### 5.4.4 Free Variables Across Yield Boundaries

If an `await` appears in the yield body, CPS splitting creates a new actor boundary. Free variables that cross this boundary are a **compiler error**:

```python
async def flow(p: dict):
    async for event in child(p):
        result = await transform(event)  # CPS split here
        result["extra"] = event["id"]    # ERROR: 'event' crosses await boundary
        yield result
```

The user must restructure to pass all needed state through the payload.

---

### 6. Code Generator Extensions

#### 6.1 Continuation Router Code

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

#### 6.2 Loop Router Code

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

#### 6.3 Streaming Event Composition Code

When the compiler detects a non-identity yield body, it generates a mutation router and sets `ASYA_PARTIAL_EVENTS_ROUTE` on the child actor.

**Example — flow with transformation:**

```python
# User code:
async def outer(p: dict):
    async for event in inner(p):
        event["reviewed"] = True
        yield event
```

**Generated mutation router** (`routers.py`):

```python
def outer_yield_router(envelope: dict) -> dict:
    """Mutation router for outer flow's yield body.

    Applies transformation to each event from 'inner' actor.
    Handles both partial and non-partial events identically.
    """
    event = envelope['payload']
    event['reviewed'] = True
    return envelope
```

**Generated deployment configuration:**

```yaml
# inner actor: partial events route through mutation router
- name: inner
  env:
    - name: ASYA_PARTIAL_EVENTS_ROUTE
      value: "outer-yield-router"

# mutation router: its own partial events go direct to gateway
- name: outer-yield-router
  env:
    - name: ASYA_PARTIAL_EVENTS_ROUTE
      value: ""  # optimized: identity after transformation
```

**Example — identity passthrough (optimized):**

```python
# User code:
async def outer(p: dict):
    async for event in inner(p):
        yield event  # no transformation
```

**No mutation router generated.** Deployment:

```yaml
- name: inner
  env:
    - name: ASYA_PARTIAL_EVENTS_ROUTE
      value: ""  # direct to gateway, zero overhead
```

---

### 7. Validated Example: ADK LLM Auditor

#### 7.1 Real ADK Code

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

#### 7.2 Equivalent Asya Async Flow

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

#### 7.3 Compiled Actor Network

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

#### 7.4 Actors Deployed

| Actor | Type | Handler | Description |
|-------|------|---------|-------------|
| `entry-router` | Generated | `routers.entry_llm_auditor` | Initializes messages, routes to `llm-call` |
| `llm-call` | User-provided | `llm_handlers.call_gemini` | Calls Gemini API with messages + tools |
| `dispatch-router` | Generated | `routers.dispatch_after_llm_call` | Checks tool_calls, routes to search or reviser |
| `google-search` | User-provided | `tools.google_search` | Executes Google Search API |
| `collect-router` | Generated | `routers.collect_after_search` | Appends tool result to messages, loops back |
| `reviser-llm-call` | User-provided | `llm_handlers.call_gemini_revise` | Calls Gemini for revision |

#### 7.5 Execution Trace

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

### 8. Compilation Levels

The compiler handles two distinct levels:

#### Level 1: Orchestration Compilation (Existing + Extended)

Translating sequential/conditional/parallel agent composition into route configurations.

```python
# ADK equivalent: SequentialAgent(sub_agents=[critic, reviser])
async def llm_auditor(state: dict) -> dict:
    state = await critic(state)
    state = await reviser(state)
    return state
```

Compiled: linear route `[critic, reviser]` -- this is what the current flow compiler already does (with `p = actor(p)` syntax), extended for `await`.

#### Level 2: Agent Decomposition (New)

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

#### Level 3: Framework Translation (Future)

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

### 9. Testing Strategy

#### 9.1 Test Principles

- **Realistic examples**: All test flows based on real ADK samples, not synthetic code
- **Compilation tests**: Verify AST parsing, IR generation, router generation, code generation
- **Execution tests**: Execute generated routers against mock envelopes, verify route manipulation
- **No infrastructure tests** in the compiler itself -- infrastructure tests live in `testing/component/flow-compiler/`

#### 9.2 Reference Test Cases

##### Test Case 1: Sequential Async Flow

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

##### Test Case 2: ReAct Loop (LLM + Tools)

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

##### Test Case 3: Conditional Async

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

##### Test Case 4: Nested Await in Conditional

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

##### Test Case 5: Multi-Tool ReAct

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

##### Test Case 6: Streaming Event Composition

Nested flows with yield body transformation:

```python
# test fixture: examples/flows/streaming_composition.py
async def outer(p: dict):
    async for event in inner(p):
        event["source"] = "outer"
        yield event

async def passthrough(p: dict):
    async for event in inner(p):
        yield event  # identity — should be optimized
```

Expected compilation:
- `outer`: generates mutation router `outer_yield_router`, sets `ASYA_PARTIAL_EVENTS_ROUTE="outer-yield-router"` on `inner`
- `passthrough`: no mutation router, sets `ASYA_PARTIAL_EVENTS_ROUTE=""` on `inner` (identity optimization)

##### Test Case 7: CPS Split Annotation

```python
# test fixture: examples/flows/no_split.py
async def flow(p: dict):
    # asya: no-split
    enriched = await local_enrich(p)  # NOT a CPS split
    p = await remote_actor(enriched)  # IS a CPS split
    return p
```

Expected: `local_enrich` call stays in-process (no actor boundary). Only `remote_actor` becomes a separate actor.

#### 9.3 Test Structure

```
testing/component/flow-compiler/
  tests/
    test_async_parser.py        # Async flow parsing
    test_await_splitting.py     # CPS transformation
    test_loop_compilation.py    # While loop -> back-edge routers
    test_yield_handling.py      # Yield event parsing and composition
    test_react_loop.py          # Full ReAct loop compilation + execution
    test_adk_llm_auditor.py     # Real ADK example validation
    test_free_variables.py      # Free variable detection (errors)
    test_streaming_composition.py  # Identity/mutation yield optimization
    test_no_split_annotation.py    # # asya: no-split handling
examples/flows/
    async_sequential.py         # Simple sequential async flow
    react_loop.py               # ReAct loop pattern
    react_multi_tool.py         # ReAct with multiple tools
    async_conditional.py        # Conditional with await
    async_nested.py             # Nested await in branches
    streaming_composition.py    # Nested flow yield composition
    no_split.py                 # CPS split annotation
    compiled/                   # Expected compilation output (golden files)
```

---

### 10. Runtime Support

#### 10.1 Async Handler Execution

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

#### 10.2 AsyncGenerator Handler Support

For generator handlers, the runtime iterates and emits each yielded event as a separate frame:

```python
if inspect.isasyncgenfunction(handler):
    async for event in handler(payload):
        send_frame(event)  # Each yield -> one frame to sidecar
else:
    result = handler(payload)
    if result is not None:
        send_frame(result)  # Single result -> one frame
```

Each yielded event becomes the `payload` of a new message. The event follows the ADK Event schema — the `partial` field determines how the sidecar routes it.

#### 10.3 Streaming Protocol (Runtime <-> Sidecar)

Current protocol: single JSON frame per handler invocation.

New protocol: multiple frames per invocation for generator handlers:

```
Frame 1: {"partial": true, "type": "text_delta", "delta": "The "}
Frame 2: {"partial": true, "type": "text_delta", "delta": "capital"}
Frame 3: {"partial": true, "type": "text_delta", "delta": " is..."}
Frame 4: {"partial": false, "text": "The capital is Paris", "messages": [...]}
```

Each frame is a complete event (no wrapper types like `"type": "stream"`). The sidecar reads the `partial` field from the event payload to determine routing:

- `partial=true` -> route via `ASYA_PARTIAL_EVENTS_ROUTE` (env var on the actor)
  - If `ASYA_PARTIAL_EVENTS_ROUTE=""` -> HTTP POST directly to gateway
  - If `ASYA_PARTIAL_EVENTS_ROUTE="router-name"` -> send to that actor's queue
- `partial=false` -> route via `route.actors` to the next actor (normal envelope routing)

If the `partial` field is absent, the event is treated as `partial=false` (backward-compatible with non-streaming handlers).

---

### 11. Sidecar Extensions

#### 11.1 Multi-Frame Protocol

Extend the Unix socket protocol to support multiple response frames from generator handlers:

```go
// Current: read one frame, route to next queue
frame := readFrame(conn)
routeToNextActor(frame)

// New: read frames until connection closes (generator exhausted)
for {
    frame, err := readFrame(conn)
    if err == io.EOF {
        return  // Generator exhausted
    }

    partial := frame.Payload["partial"]
    if partial == true {
        routePartialEvent(frame, envelopeID)
    } else {
        routeToNextActor(frame)  // Normal envelope routing
    }
}
```

#### 11.2 Partial Event Routing

The sidecar reads `ASYA_PARTIAL_EVENTS_ROUTE` from its environment to determine where partial events go:

```go
func routePartialEvent(frame Frame, envelopeID string) {
    route := os.Getenv("ASYA_PARTIAL_EVENTS_ROUTE")
    if route == "" {
        // Direct to gateway — zero-hop streaming
        forwardToGateway(frame.Payload, envelopeID)
    } else {
        // Route through mutation router queue
        sendToQueue(route, frame.Payload, envelopeID)
    }
}
```

**Direct-to-gateway path** (`ASYA_PARTIAL_EVENTS_ROUTE=""`):

```
POST /api/v1/envelopes/{envelope_id}/events
Content-Type: application/json

{"partial": true, "type": "text_delta", "delta": "The capital"}
```

The gateway pushes these to connected SSE/WebSocket clients.

**Mutation router path** (`ASYA_PARTIAL_EVENTS_ROUTE="router-name"`):

The partial event is wrapped in a new envelope and sent to the mutation router's queue. The mutation router transforms it, and its sidecar then re-evaluates routing based on the (possibly modified) `partial` field and its own `ASYA_PARTIAL_EVENTS_ROUTE` setting. This enables chained transformations across nested flows.

#### 11.3 Non-Partial Event Routing

Non-partial events (`partial=false` or absent) follow the existing `route.actors` routing:

- If `route.current < len(route.actors)` -> send to next actor's queue
- If route exhausted -> send to `happy-end` queue

This is unchanged from the current sidecar behavior.

---

### 12. Compiler Pipeline Summary

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

### 13. Scope and Phasing

#### Phase 1: Parser Extensions (Foundation)
- IR: New node types (AwaitCall, WhileLoop, YieldEvent, AsyncFlowFunction)
- Parser: `async def` detection
- Parser: `await` expression recognition
- Parser: `while` loop recognition
- Parser: `yield` expression recognition
- **Test**: Parsing test cases, verify IR output

#### Phase 2: CPS Transformation (Core)
- Grouper: CPS split at await boundaries -> continuation routers
- Grouper: Loop back-edge generation for while loops
- CodeGen: Continuation router code generation
- CodeGen: Loop router code generation
- **Test**: Compilation of all reference test cases, execution against mock envelopes

#### Phase 3: Streaming Event Composition
- Compiler: Identity yield optimization (static analysis of yield bodies)
- Compiler: Mutation router generation for non-identity yields
- Compiler: `ASYA_PARTIAL_EVENTS_ROUTE` configuration in deployment output
- Runtime: AsyncGenerator multi-frame response (each yield = one frame)
- Sidecar: Multi-frame protocol (read frames until EOF)
- Sidecar: `partial` field routing (`ASYA_PARTIAL_EVENTS_ROUTE` or `route.actors`)
- Sidecar: Direct-to-gateway HTTP for `ASYA_PARTIAL_EVENTS_ROUTE=""`
- **Test**: Streaming composition tests (identity passthrough, mutation routers, nested flows)

#### Phase 4: Integration and Validation
- Full ADK LLM Auditor example: compile + deploy + test
- ReAct loop with real tool actors
- Component tests with mock LLM and tool actors
- Documentation and examples

#### Future (Out of Scope)
- Free variable analysis and auto-serialization (across `await` boundaries and in yield bodies)
- ADK declarative syntax recognition (Level 3 compilation)
- Typed handler signatures (`def get_weather(city: str) -> str`)
- Parallel fan-out (`asyncio.gather`, list comprehension fan-out) — see [Fan-In/Fan-Out RFC](../fan-in/asya-fan-in-fan-out.md)
- Try-catch error routing
- Fire-and-forget `await` (side-effect-only actor calls)
- Partial event ordering guarantees across queue-routed mutation chains

---

### 14. Open Questions

1. **`for` loop handling**: Should `for tc in response.tool_calls` be unrolled or handled as a loop? For now, we assume single tool call per iteration (the router dispatches to one tool at a time).

2. **Multiple tool calls per LLM response**: LLMs can return multiple tool calls. Should the dispatch router:
   - (A) Process them sequentially (simpler, one at a time)?
   - (B) Fan-out to parallel tool actors (requires fan-in aggregation)?
   Decision deferred. Start with (A).

3. **Payload growth**: Messages array grows with each loop iteration. Need payload size monitoring and eventual compression (reference: asya-bi8 session state strategy -- binary protocol, artifact offloading).

4. **Loop termination**: What happens if the LLM never stops calling tools? Need `max_iterations` equivalent. The `while True` loop should have a compiler-enforced or runtime-enforced iteration limit.

5. **Error in tool actor**: If a tool actor fails, should the loop retry, break, or route to error-end? Currently, errors always go to error-end. Should the dispatch router support error recovery?

6. **`ASYA_PARTIAL_EVENTS_ROUTE` and multi-namespace**: Queue names include namespace prefix (`asya-{namespace}-{actor}`). How does `ASYA_PARTIAL_EVENTS_ROUTE` resolve across namespaces? Should it use fully qualified names, or should the sidecar resolve relative names within its own namespace?

7. **Fire-and-forget `await`**: Currently unsupported — `await actor(p)` where the result is discarded (not assigned) is a compiler error. Should this be supported in the future as a side-effect-only actor call?

8. **Free variable auto-serialization in yield bodies**: When an `await` in a yield body creates a CPS split, free variables crossing the boundary are currently a compiler error. Future: should the compiler auto-serialize them into the event payload (similar to Section 2.3)?

9. **Partial event ordering guarantees**: When partial events flow through mutation routers (queue-based), ordering is not guaranteed by queue semantics. Should the runtime attach sequence numbers? Or is ordering only guaranteed for direct-to-gateway (HTTP) streaming?

---

### 15. References

- [Flow Compiler Source](../../../src/asya-cli/asya_cli/flow/) -- Current compiler implementation
- [Handler Signatures RFC](../asya-handler-signatures.md) -- Typed signatures design
- [Framework Comparison](../asya-handler-syntax-comparisons.md) -- 14-framework survey
- [Agentic Asya RFC](../asya-bi8-agentic-asya.md) -- Dual-channel streaming architecture
- [ADK Sequential Agent](https://github.com/google/adk-python/blob/main/src/google/adk/agents/sequential_agent.py)
- [ADK LLM Auditor Sample](https://github.com/google/adk-samples/tree/main/python/agents/llm-auditor)
- [ADK BaseLlmFlow](https://github.com/google/adk-python/blob/main/src/google/adk/flows/llm_flows/base_llm_flow.py)
- [PEP 525 -- Asynchronous Generators](https://peps.python.org/pep-0525/)

## ADR: AsyncFlow — CRD vs Labels

This ADR decided to use labels + CLI tooling instead of an AsyncFlow CRD for flow management.

---

### 1. Context

Asya actors are flat: each `AsyncActor` claim is an independent unit with its own queue, deployment, and scaling config. The Flow DSL compiler (`asya flow compile`) generates **router actors** that implement branching and sequencing logic, plus references to **processor actors** that perform actual work.

We needed a mechanism to:
- **Group actors** belonging to the same flow (for queries, lifecycle, observability)
- **Deploy and get status of flows** as coherent units (routers + processors + gateway config)
- **Expose flows** as MCP tools via the gateway
- **Support GitOps** (declarative, reproducible, auditable)

Two approaches were evaluated in depth: an AsyncFlow Crossplane XRD, and a label-based convention managed by CLI tooling.

---

### 2. Proposed Architecture: AsyncFlow XRD (Rejected)

#### 2.1. Schema

AsyncFlow would be a Crossplane XRD in the `asya.sh` API group with claims:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncFlow
metadata:
  name: order-processing
spec:
  transport: sqs
  entrypoint: validate-order

  # Referenced actors (not owned, must exist)
  processors:
    - actor: validate-order
    - actor: payment-processor

  # Router code — mutually exclusive with routerCodeRefs
  routerCode:
    configMapRef:
      name: order-processing-routers    # existing ConfigMap

  # MCP gateway exposure
  expose:
    enabled: true
    tool:
      name: process-order
      description: "Submit an order for processing"
      parameters:
        type: object
        properties:
          order_id: { type: string }

status:
  phase: Ready            # Creating | Ready | Degraded
  actors:
    ready: 7
    total: 9
  exposed: true
  entrypointQueue: "asya-prod-validate-order"
```

Naming: `AsyncFlow` / `asyncflows` / `asyf`.

#### 2.2. Mixed Ownership Model

The composition would create **router** actors (owned, deleted with the flow) and **reference** processor actors (not owned, observed via `managementPolicies: ["Observe"]`). This mirrors the existing `workload` / `workloadRef` pattern in `AsyncActor`.

#### 2.3. Three-Phase Implementation

The plan was to progressively enhance AsyncFlow from passive to fully active:

**Phase 1 — Passive XRD**: Schema-only. Composition creates routers and ConfigMaps. No status aggregation, no actor discovery. The XRD is a declaration of intent — "these actors form a flow" — but provides no runtime intelligence. This is similar to how early CRDs worked before controllers were written for them.

**Phase 2 — Semi-active (function-extra-resources)**: Add `function-extra-resources` to the composition pipeline. This Crossplane function reads arbitrary cluster resources during composition, enabling:
- Actor discovery by label selector (`asya.sh/flow=<name>`)
- Status aggregation (count ready/total actors, compute flow phase)
- No custom code — uses existing Crossplane functions (`function-extra-resources` + `function-go-templating`)

**Phase 3 — Fully active (custom composition function)**: Write a Go composition function (~200 LOC) implementing the Crossplane Function SDK. This enables:
- Resolve actors by name (not just label selector)
- M:N flow membership (one actor in multiple flows)
- Lifecycle management with finalizers
- Full status reporting with per-actor readiness

#### 2.4. GatewayConfig Aggregator XRD

A hidden singleton XRD (`internal.asya.sh` API group, no claim names, no categories) would aggregate exposed AsyncFlow configs into a single gateway ConfigMap:

```
AsyncFlow (exposed: true)  ─┐
AsyncFlow (exposed: true)  ─┤──► GatewayConfig XRD ──► ConfigMap "gateway-tools"
AsyncFlow (exposed: true)  ─┘         │                        │
                                       │                        ▼
                              function-extra-resources    Gateway pod
                              + function-go-templating    (fsnotify reload)
```

The composition pipeline:
1. `function-extra-resources`: reads AsyncFlow XRs with `expose.enabled: true`
2. `function-go-templating`: aggregates tool definitions from all matching flows
3. Emits a `provider-kubernetes Object` — a ConfigMap mounted into the gateway pod

Hiding mechanisms: no `claimNames` (cluster-scoped only), `internal.asya.sh` API group, no `categories`, RBAC-restricted, auto-created by Helm chart.

#### 2.5. Why This Was Attractive

- **Self-documenting**: `kubectl explain asyncflow.spec` describes all fields
- **Single entity**: `kubectl get asyncflow` shows all flows with status columns
- **Validated schema**: XRD enforces structure at admission time
- **Status aggregation**: Phases 2-3 provide real-time flow health
- **Kubernetes-native**: "If it has identity, state, and lifecycle, it should be a resource"

---

### 3. Chosen Architecture: Labels + CLI (Accepted)

#### 3.1. Label Convention

Every actor belonging to a flow carries these labels:

| Label | Purpose | Values |
|-------|---------|--------|
| `asya.sh/flow` | Flow membership (1:M) | Flow name (e.g., `order-processing`) |
| `asya.sh/flow-role` | Role within flow | `entrypoint`, `exitpoint`, `router`, `processor` |

Annotations for richer metadata:

| Annotation | Purpose |
|------------|---------|
| `asya.sh/flow-tool` | MCP tool name (if exposed) |
| `asya.sh/flow-description` | Tool description (from flow.py docstring) |

#### 3.2. 1:M Constraint

An actor can belong to **at most one flow**. This makes `asya.sh/flow` a reliable foreign key — queryable, indexable, always accurate.

If the same handler logic is needed in multiple flows, the actor is **cloned** (new name, same image/handler, flow-specific scaling config). This is the Kubernetes-native approach — you don't share a Deployment across Services with different scaling requirements either.

#### 3.3. CLI Commands

```bash
# Compile flow DSL to routers
asya flow compile order_flow.py --output-dir compiled/

# Deploy: generate manifests and/or apply to cluster
asya flow deploy compiled/ \
  --flow-name order-processing \
  --namespace prod \
  --transport sqs \
  --output-dir manifests/        # for GitOps: generate files

# Expose flow as MCP tool (updates gateway ConfigMap)
asya expose order-processing

# Undeploy: delete all flow resources
asya flow undeploy order-processing -n prod
```

What `asya flow deploy` generates:
1. **AsyncActor manifests for routers** — new resources with `asya.sh/flow` and `asya.sh/flow-role=router` labels
2. **AsyncActor manifests for processors** — creates new or updates existing to add `asya.sh/flow` label
3. **ConfigMap for router code** — `routers.py` content, labeled with `asya.sh/flow`
4. **ConfigMap for flow metadata** — optional, for gateway exposure

#### 3.4. GitOps Workflow

The CLI generates **manifest files**, not cluster mutations:

```
DS laptop                         Git repo                    Cluster
───────                          ────────                    ───────
asya flow compile flow.py
        │
        ▼
asya flow deploy compiled/ \
  --output-dir manifests/
        │
        ▼
manifests/
├── router-start.yaml          ──► git add && commit ──► ArgoCD ──► kubectl apply
├── router-line-4-if.yaml              │
├── validate-order.yaml                │
├── payment-processor.yaml             │
└── routers-configmap.yaml             ▼
                                  Source of truth
```

For experimentation (no GitOps): omit `--output-dir`, CLI applies directly to cluster.

#### 3.5. Gateway Tool Registration

Instead of a GatewayConfig aggregator XRD, the gateway mounts a singleton ConfigMap (`gateway-tools`). The CLI updates it:

```bash
asya expose order-processing
# 1. Finds entrypoint actor by label: asya.sh/flow-role=entrypoint
# 2. Reads tool name from annotation (or derives from flow name)
# 3. Detects description from flow.py docstring
# 4. Detects parameters from flow.py function signature
# 5. Patches gateway-tools ConfigMap
# 6. Kubelet syncs to mounted volume → fsnotify → gateway reloads
```

---

### 4. Decision Rationale

#### 4.1. Flow Topology Is an Application Concern

The critical insight: **flow routing logic lives in `routers.py` — Python code inside the actor, not Kubernetes resources**. The K8s level only needs to know "which actors participate in this flow" (an unordered set with role annotations), not the flow's branching structure, conditions, or sequencing.

An AsyncFlow CRD would replicate application-level topology at the Kubernetes level — creating a dual source of truth that nobody would read directly (it's generated by `asya-cli`). This violates the principle of having one authoritative source per concern.

#### 4.2. XRD Has the Same GitOps Problem for Referenced Actors

A key discovery during design: even with an AsyncFlow XRD, referenced processor actors still need `asya.sh/flow` labels in their manifests for searchability. The XRD can set labels at runtime via composition, but then GitOps manifests in git don't match cluster state (drift). To avoid drift, you must update processor manifests in git anyway — the same work as the labels-only approach.

The XRD adds a layer of indirection without actually simplifying the GitOps story for referenced (non-owned) actors.

#### 4.3. Passive CRD Provides No Status Anyway

A passive XRD (Phase 1) has no controller logic — no status aggregation, no health checks, no drift detection. It's a schema with no runtime intelligence. The value proposition of a CRD ("single entity with status") requires Phases 2-3, which are significant engineering effort for uncertain payoff at this stage.

#### 4.4. Labels Naturally Model Unordered Set Membership

The relationship between a flow and its actors is: "these actors participate in this flow." This is an **unordered set membership** — exactly what Kubernetes labels are designed for. Adding role distinctions (`entrypoint`, `router`, `processor`) via `asya.sh/flow-role` provides the necessary structure without a CRD.

Discovery works natively:
```bash
kubectl get asya -l asya.sh/flow=order-processing
kubectl get asya -l asya.sh/flow=order-processing,asya.sh/flow-role=entrypoint
kubectl delete asya -l asya.sh/flow=order-processing
```

#### 4.5. 1:M Makes Labels Reliable

The decision to constrain actor-flow relationships to 1:M (one actor belongs to at most one flow) is what makes the labels-only approach viable. With M:N, `asya.sh/flow` would hold only one of potentially many flow names — unreliable for queries. With 1:M, the label is a true foreign key.

Actor cloning (deploying the same handler logic under a different actor name) is not a workaround but the correct Kubernetes pattern: different flows will likely need different scaling, resources, and queue configs for the same handler logic anyway.

#### 4.6. Premature Abstraction Risk

We don't yet know:
- What status fields flows actually need in production
- Whether flows should compose (flow-of-flows)
- What the gateway exposure schema should look like at scale
- What OTEL tracing needs from flow identity
- Whether 1:M is the right long-term constraint

Committing to a CRD schema now risks building the wrong abstraction. Labels establish the **convention** (`asya.sh/flow=name`). A future CRD can adopt this convention and add structure on top — the migration is additive and non-breaking.

---

### 5. What We Lose

| Capability | Impact | Mitigation |
|-----------|--------|------------|
| `kubectl get asyncflow` | No single-resource view of flows | `kubectl get asya -l asya.sh/flow=X` |
| `kubectl explain asyncflow.spec` | No self-documenting schema | `asya flow --help` provides discoverability |
| Admission validation | No schema enforcement on flow structure | CLI validates during `asya flow deploy` |
| Status aggregation | No real-time flow health | Query individual actors; passive CRD wouldn't have status either |
| Single-resource deletion | Must use label selector | `kubectl delete asya -l asya.sh/flow=X` or `asya flow undeploy X` |
| GatewayConfig XRD | No automatic aggregation | CLI updates singleton ConfigMap directly |

---

### 6. What We Gain

| Benefit | Detail |
|---------|--------|
| Zero new CRDs | No XRD, composition, or provider-kubernetes Objects to maintain |
| No three-phase rollout | Labels work immediately — no progressive enhancement needed |
| Simpler gateway | Singleton ConfigMap updated by CLI, no aggregation composition |
| GitOps-native | Manifest files with labels in git — ArgoCD/Flux apply directly |
| Reduced user cognitive load | No new resource type to learn; just labels on existing AsyncActors |
| Future design freedom | Can introduce AsyncFlow CRD later with real usage data informing the schema |
| Flat actor mesh | Actors remain the primary abstraction; flows are a labeling convention, not a hierarchy |

---

### 7. Core Insights

These observations shaped the decision and should inform future revisitation:

**Labels as stable API.** The label convention (`asya.sh/flow=name`) is the contract. Whether a CLI or a CRD controller manages that label is an implementation detail. This is how the K8s ecosystem works: labels like `app.kubernetes.io/name` existed before any controller enforced them. Establishing the convention now enables a future CRD to adopt it without breaking changes.

**Generator vs Controller.** `asya flow deploy` is a generator (like `helm template` or `kubectl create deployment`), not a controller. It produces declarative resources. The controllers (Crossplane composition for AsyncActor, ArgoCD for GitOps) handle reconciliation. This separation keeps the CLI stateless and the reconciliation loop in proven systems.

**Layer separation.** Routing topology (which actor calls which, under what conditions) is application logic in `routers.py`. Infrastructure grouping (which actors participate in a flow) is a Kubernetes concern addressed by labels. AsyncFlow CRD would bridge these layers, creating dual sources of truth. Keeping them separate means each layer is independently evolvable.

**The CRD question.** "If something has identity, state, and lifecycle, it should be a resource" — but this applies only when cluster-level reconciliation adds value. Flows have identity (the label value) and lifecycle (deploy/undeploy), but their "state" is the aggregate state of their constituent actors, which already have individual status tracking. A CRD adds value when you need **automated reactions** to state changes (auto-healing, drift detection, cascading status). Until that need is demonstrated, the CRD is overhead.

**1:M is the enabler.** The M:N vs 1:M constraint on actor-flow membership is the pivotal decision. M:N makes labels unreliable (a label key holds one value) and requires a junction table (CRD). 1:M makes labels reliable and eliminates the need for the junction table entirely. Actor cloning (deploying the same handler under a flow-specific name) is not a cost — it's the correct pattern, since different flows need different scaling/resource configs for the same logic.

**YAGNI at the CRD level.** The label convention supports a future CRD without requiring it now. The escape hatch: introduce an AsyncFlow CRD whose composition reads and manages `asya.sh/flow` labels. The migration is: "wrap existing labeled resources in a CRD." No schema to migrate, no data to convert — just add a new resource that manages what the CLI used to manage.

---

### 8. Migration Path to AsyncFlow CRD (If Needed)

If cluster-level reconciliation becomes necessary (status aggregation, auto-healing, drift detection), the CRD can be introduced incrementally:

1. Define AsyncFlow XRD with a schema informed by real usage patterns
2. Composition creates/observes actors using the same `asya.sh/flow` label convention
3. `asya flow deploy` generates AsyncFlow YAML instead of individual actor manifests
4. Existing label-based queries (`kubectl get asya -l asya.sh/flow=X`) continue working
5. GatewayConfig XRD can aggregate AsyncFlows instead of the CLI updating a ConfigMap

Triggers for this migration:
- Multiple teams sharing clusters need RBAC on flow-level operations
- SRE requires `kubectl get asyncflow` dashboard with status columns
- Flow health needs automated alerting (not just manual queries)
- Flow lifecycle events need to trigger external systems (webhooks, notifications)

---

### 9. References

- [RFC: Crossplane Architecture](rfc-crossplane.md) — Overall migration from custom operator to Crossplane
- [RFC: Dual-Mode Deployment](thoughts-gitops-dev-flow.md) — Imperative-to-GitOps promotion workflow
- [Flow Compiler Architecture](../architecture/asya-flow.md) — How flow DSL compiles to router actors
- Crossplane [function-extra-resources](https://github.com/crossplane-contrib/function-extra-resources) — Reads arbitrary K8s resources during composition
- Crossplane [provider-kubernetes](https://github.com/crossplane-contrib/provider-kubernetes) — Creates K8s resources from compositions

---
_Migrated from beads `asya-4ozl`_
