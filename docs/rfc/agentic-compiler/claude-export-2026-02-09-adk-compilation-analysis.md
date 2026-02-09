# Claude Code Conversation Export

**Date**: 2026-02-09
**Working Directory**: /home/a.yushkovskiy/asya/.worktrees/rfc0
**Topic**: Compiling ADK-Style Agents to Asya Actor Networks

---

## Assistant

### Research: Fetching Real ADK Source Code

To validate the prototype against real examples, I fetched ADK's actual source code and samples in parallel.

<details>
<summary>Tool: WebFetch - ADK SequentialAgent source</summary>

**URL**: `https://raw.githubusercontent.com/google/adk-python/8d0279251ce4fad6f0c84bd7777eb5a74f7ba07a/src/google/adk/agents/sequential_agent.py`

**Result**: Complete source code of SequentialAgent. Key method:

```python
@override
async def _run_async_impl(
    self, ctx: InvocationContext
) -> AsyncGenerator[Event, None]:
    if not self.sub_agents:
        return

    agent_state = self._load_agent_state(ctx, SequentialAgentState)
    start_index = self._get_start_index(agent_state)

    pause_invocation = False
    resuming_sub_agent = agent_state is not None
    for i in range(start_index, len(self.sub_agents)):
        sub_agent = self.sub_agents[i]
        if not resuming_sub_agent:
            if ctx.is_resumable:
                agent_state = SequentialAgentState(current_sub_agent=sub_agent.name)
                ctx.set_agent_state(self.name, agent_state=agent_state)
                yield self._create_agent_state_event(ctx)

        async with Aclosing(sub_agent.run_async(ctx)) as agen:
            async for event in agen:
                yield event
                if ctx.should_pause_invocation(event):
                    pause_invocation = True

        if pause_invocation:
            return

        resuming_sub_agent = False

    if ctx.is_resumable:
        ctx.set_agent_state(self.name, end_of_agent=True)
        yield self._create_agent_state_event(ctx)
```

</details>

<details>
<summary>Tool: WebFetch - ADK BaseAgent source</summary>

**URL**: `https://raw.githubusercontent.com/google/adk-python/8d0279251ce4fad6f0c84bd7777eb5a74f7ba07a/src/google/adk/agents/base_agent.py`

**Result**: BaseAgent provides two entry points:
- `run_async` (marked `@final`): Creates invocation context, executes before/after callbacks, invokes `_run_async_impl`
- `run_live`: Similar but for audio/video-based conversation

Subclasses implement `_run_async_impl` as async generators yielding `Event` objects. Sub-agent invocation occurs within `_run_async_impl` implementations.

</details>

<details>
<summary>Tool: WebFetch - ADK LoopAgent source</summary>

**URL**: `https://raw.githubusercontent.com/google/adk-python/8d0279251ce4fad6f0c84bd7777eb5a74f7ba07a/src/google/adk/agents/loop_agent.py`

**Result**: LoopAgent runs sub-agents in a loop with `max_iterations`. Tracks loop count in `LoopAgentState`. Handles escalation signals and pause requests. Resets sub-agent states between iterations.

</details>

<details>
<summary>Tool: WebFetch - ADK ParallelAgent source</summary>

**URL**: `https://raw.githubusercontent.com/google/adk-python/8d0279251ce4fad6f0c84bd7777eb5a74f7ba07a/src/google/adk/agents/parallel_agent.py`

**Result**: ParallelAgent runs sub-agents concurrently using `asyncio.TaskGroup` (Python 3.11+) or manual task management (3.10-). Creates branch contexts for isolation. Yields events from all branches.

</details>

<details>
<summary>Tool: WebFetch - ADK LlmAgent source</summary>

**URL**: `https://raw.githubusercontent.com/google/adk-python/8d0279251ce4fad6f0c84bd7777eb5a74f7ba07a/src/google/adk/agents/llm_agent.py`

**Result**: LlmAgent's `_run_async_impl` delegates the actual ReAct loop to `_llm_flow` (either `SingleFlow` or `AutoFlow`). The agent handles state loading/saving and sub-agent resume logic, but the tool-calling loop lives in the flow objects.

</details>

<details>
<summary>Tool: WebFetch - ADK BaseLlmFlow source</summary>

**URL**: `https://raw.githubusercontent.com/google/adk-python/8d0279251ce4fad6f0c84bd7777eb5a74f7ba07a/src/google/adk/flows/llm_flows/base_llm_flow.py`

**Result**: `BaseLlmFlow.run_async()` implements the ReAct loop:
1. Loop: call `_run_one_step_async()` which calls the LLM
2. Detection: `model_response_event.get_function_calls()` identifies tool invocations
3. Execution: `_postprocess_handle_function_calls_async()` processes tools and returns responses
4. Loop continuation: Function responses feed back into the event stream, triggering subsequent LLM calls
5. Exit: Final response (`is_final_response()`) breaks the loop

</details>

<details>
<summary>Tool: WebFetch - ADK Samples listing</summary>

**URL**: `https://github.com/google/adk-samples/tree/main/python/agents`

**Result**: 43 sample agents including: brand-search-optimization, customer-service, deep-search, llm-auditor, order-processing, travel-concierge, parallel_task_decomposition_execution, and many more.

</details>

<details>
<summary>Tool: WebFetch - LLM Auditor agent.py</summary>

**URL**: `https://raw.githubusercontent.com/google/adk-samples/main/python/agents/llm-auditor/llm_auditor/agent.py`

**Result**:

```python
from google.adk.agents import SequentialAgent
from .sub_agents.critic import critic_agent
from .sub_agents.reviser import reviser_agent

llm_auditor = SequentialAgent(
    name="llm_auditor",
    description=(
        "Evaluates LLM-generated answers, verifies actual accuracy using the"
        " web, and refines the response to ensure alignment with real-world"
        " knowledge."
    ),
    sub_agents=[critic_agent, reviser_agent],
)

root_agent = llm_auditor
```

</details>

<details>
<summary>Tool: WebFetch - LLM Auditor critic_agent</summary>

**URL**: `https://raw.githubusercontent.com/google/adk-samples/main/python/agents/llm-auditor/llm_auditor/sub_agents/critic/agent.py`

**Result**: `critic_agent` is an `Agent(model="gemini-2.5-flash")` with Google Search as a tool and `_render_reference` as an after-model callback that formats citations with markdown links.

</details>

<details>
<summary>Tool: WebFetch - LLM Auditor reviser_agent</summary>

**URL**: `https://raw.githubusercontent.com/google/adk-samples/main/python/agents/llm-auditor/llm_auditor/sub_agents/reviser/agent.py`

**Result**: `reviser_agent` is an `Agent(model="gemini-2.5-flash")` with a `_remove_end_of_edit_mark` callback that strips `---END-OF-EDIT---` markers from responses.

</details>

<details>
<summary>Tool: WebFetch - Brand Search Optimization agent.py</summary>

**URL**: `https://raw.githubusercontent.com/google/adk-samples/main/python/agents/brand-search-optimization/brand_search_optimization/agent.py`

**Result**: Root agent with `sub_agents=[keyword_finding_agent, search_results_agent, comparison_root_agent]`. Uses `Agent` (not `SequentialAgent`), meaning the LLM decides which sub-agent to invoke via agent transfer.

</details>

<details>
<summary>Tool: WebFetch - Travel Concierge agent.py</summary>

**URL**: `https://raw.githubusercontent.com/google/adk-samples/main/python/agents/travel-concierge/travel_concierge/agent.py`

**Result**: Root agent with 6 sub-agents (inspiration, planning, booking, pre-trip, in-trip, post-trip). Uses `Agent` with LLM-based routing, not sequential execution.

</details>

---

### Key Insight: ADK Internals

> **What I learned from studying ADK internals (real source code, not docs):**
>
> 1. **ADK's orchestration agents are surprisingly simple** -- `SequentialAgent._run_async_impl` is just a `for` loop over sub-agents, yielding their events. `LoopAgent` wraps that in another loop with `max_iterations`. `ParallelAgent` uses `asyncio.TaskGroup`. The complexity lives in `BaseLlmFlow`, which handles the ReAct loop (call LLM -> detect tool calls -> execute -> feed back -> repeat).
>
> 2. **All ADK orchestration works by generator composition** -- a parent agent yields events from child agents via `async for event in sub_agent.run_async(ctx): yield event`. This is in-process generator nesting -- which fundamentally **cannot work** in a distributed system where each agent runs on a different pod.
>
> 3. **ADK's tool execution is in-process too** -- when `BaseLlmFlow` detects a tool call, it executes the tool function locally and feeds the result back. No message passing, no queues.

---

## Analysis: Compiling ADK-Style Agents to Asya Actor Networks

### The Real ADK Examples

**Example 1: LLM Auditor** (the cleanest multi-agent sample)

```python
# ADK declarative code (from adk-samples/llm-auditor)
from google.adk.agents import SequentialAgent

llm_auditor = SequentialAgent(
    name="llm_auditor",
    sub_agents=[critic_agent, reviser_agent],
)
```

Where:
- `critic_agent` = `Agent(model="gemini-2.5-flash", tools=[google_search], instruction="...", after_model_callback=_render_reference)`
- `reviser_agent` = `Agent(model="gemini-2.5-flash", instruction="...", after_model_callback=_remove_end_of_edit_mark)`

**Example 2: Brand Search Optimization** (hierarchical multi-agent)

```python
root_agent = Agent(
    model="...",
    sub_agents=[keyword_finding_agent, search_results_agent, comparison_root_agent],
    instruction=ROOT_PROMPT,
)
```

Here the root agent is an `LlmAgent` (not `SequentialAgent`), meaning the LLM itself decides which sub-agent to invoke via **agent transfer** -- essentially an LLM-powered router.

### What ADK does internally at SequentialAgent level

From the actual `sequential_agent.py` source:

```python
async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
    for i in range(start_index, len(self.sub_agents)):
        sub_agent = self.sub_agents[i]
        async with Aclosing(sub_agent.run_async(ctx)) as agen:
            async for event in agen:
                yield event
                if ctx.should_pause_invocation(event):
                    return
```

This is **generator composition** -- the parent yields child events. Each `sub_agent.run_async(ctx)` returns an async generator. The parent iterates it, forwarding events.

### The Key Transformation: CPS (Continuation-Passing Style)

The user's vision is to take an async function and treat each `await` as a split point. This is essentially **CPS transformation applied to message passing**:

```
                      async function                          actor network
                      ──────────────                          ─────────────
                 ┌─ code before await ─┐              ┌─ Actor A (router) ─┐
                 │                     │              │ prepares payload,   │
                 │ state = await X()   │  ──compile──>│ sends to X         │
                 │                     │              └────────────────────┘
                 │ code after await    │              ┌─ Actor X           ─┐
                 │ state = await Y()   │              │ does work, returns  │
                 │                     │              └────────────────────┘
                 │ return state        │              ┌─ Continuation Rtr  ─┐
                 └─────────────────────┘              │ receives X result,  │
                                                      │ sends to Y          │
                                                      └────────────────────┘
```

Each `await` splits the function into:
- **Before-await** -> current actor (does work, sends message)
- **After-await** -> continuation actor (receives result, continues)

### Applying to the LLM Auditor

**Step 1: User writes the Asya async flow** (simplified version of ADK's SequentialAgent):

```python
# asya flow (async version)
async def llm_auditor(state: dict) -> dict:
    state = await critic(state)     # await split #1
    state = await reviser(state)    # await split #2
    return state
```

**Step 2: But `critic` is an LLM agent with tools.** The user writes its event loop too:

```python
async def critic(state: dict) -> AsyncGenerator[dict, None]:
    messages = state.get("messages", [{"role": "user", "content": state["query"]}])

    while True:
        response = await llm_call(messages, model="gemini-2.5-flash")  # await split

        if response.tool_calls:
            for tc in response.tool_calls:
                result = await google_search(**tc.args)  # await split
                messages.append({"role": "tool", "content": result, "tool_call_id": tc.id})
        else:
            # Last yield = control event (Option B convention)
            yield {"type": "result", "critique": response.text, "messages": messages}
            return
```

**Step 3: Compiler decomposes at each `await`**

The compiler sees:
1. `await llm_call(...)` -> split: send to LLM actor, finish
2. `await google_search(...)` -> split: send to tool actor, finish
3. `while True` -> loop: generate a router that loops back
4. `if response.tool_calls` -> conditional: generate a dispatch router
5. `yield {"type": "result", ...}` -> final event: pass to next actor in parent flow

**Step 4: Generated actor network**

```
                     ┌──────────────────────────────────────────────┐
                     │              LLM AUDITOR FLOW                │
                     │                                              │
 ┌─────────────┐    │  ┌──────────┐    ┌──────────────────┐       │
 │ entry-router │───>│  │ llm-call │───>│ dispatch-router  │       │
 └─────────────┘    │  └──────────┘    └───┬──────────┬───┘       │
                     │                      │          │            │
                     │          tool_calls  │          │  no tools  │
                     │                      v          │            │
                     │             ┌──────────────┐    │            │
                     │             │google-search │    │            │
                     │             └──────┬───────┘    │            │
                     │                    │            │            │
                     │                    v            │            │
                     │            ┌──────────────┐     │            │
                     │            │collect-router│     │            │
                     │            └──────┬───────┘     │            │
                     │                   │             │            │
                     │         ┌─────────┘             │            │
                     │         │(loop back)            │            │
                     │         v                       v            │
                     │    [llm-call]             ┌──────────┐       │
                     │                          │ reviser  │       │
                     │                          │ llm-call │       │
                     │                          └─────┬────┘       │
                     │                                │            │
                     └────────────────────────────────┼────────────┘
                                                      │
                                                      v
                                                 (happy-end)
```

**Actors deployed:**

| Actor | Type | What it does |
|-------|------|-------------|
| `entry-router` | Generated router | Initializes messages array if needed, routes to `llm-call` |
| `llm-call` | LLM actor | Calls Gemini with messages + tools, returns response |
| `dispatch-router` | Generated router | Checks `response.tool_calls`: if yes -> `google-search`, if no -> `reviser-llm-call` |
| `google-search` | Tool actor | Executes Google Search API, returns result |
| `collect-router` | Generated router | Appends tool result to messages, routes back to `llm-call` (loop) |
| `reviser-llm-call` | LLM actor | Calls Gemini with critique + original query, returns revised answer |

**State traveling in payload:**

```json
{
  "query": "What is the capital of France?",
  "messages": [
    {"role": "user", "content": "What is the capital of France?"},
    {"role": "assistant", "content": null, "tool_calls": [{"name": "google_search", "args": {"query": "capital of France"}}]},
    {"role": "tool", "content": "Paris is the capital of France...", "tool_call_id": "tc_1"},
    {"role": "assistant", "content": "The capital of France is Paris..."}
  ],
  "critique": "The answer is factually correct. References: [1] ...",
  "revised_answer": "Paris is the capital of France. [Source: ...]"
}
```

Every actor is **stateless**. The full conversation state travels in the payload. Any of the 100 pods of `llm-call` can pick up the next iteration.

### The Compiler's Job: Decomposing at `await`

Here's what the compiler does, step by step:

```python
# INPUT: User's async function
async def critic(state: dict) -> AsyncGenerator[dict, None]:
    messages = state.get("messages", [])          # <- mutation (batched into router)

    while True:                                    # <- loop construct
        response = await llm_call(messages)        # <- SPLIT: actor "llm-call"

        if response.tool_calls:                    # <- conditional (router)
            for tc in response.tool_calls:
                result = await google_search(tc)    # <- SPLIT: actor "google-search"
                messages.append(tool_result(tc, result))  # <- mutation (collect-router)
        else:
            yield {"type": "result", ...}          # <- control event -> next actor
            return
```

**Compiler output -- pseudo-IR:**

```
BLOCK entry:
    mutation: messages = state.get("messages", [])
    goto: llm_call

BLOCK llm_call:
    actor: llm_call(messages) -> response
    goto: dispatch

BLOCK dispatch:
    if response.tool_calls:
        goto: google_search
    else:
        emit_result(state)
        goto: NEXT_IN_PARENT  # returns to parent flow

BLOCK google_search:
    actor: google_search(tc.args) -> result
    goto: collect

BLOCK collect:
    mutation: messages.append(tool_result(tc, result))
    goto: llm_call  # loop back
```

Each BLOCK becomes either an **actor** (if it has `actor:`) or a **generated router** (if it only has mutations/conditionals/gotos).

### Validation: Does This Work?

Validating against the real LLM Auditor scenario:

**Scenario**: User asks "What is the capital of France?" and the LLM answer might be wrong.

**Execution trace:**

1. **entry-router**: Payload `{"query": "What is..."}` -> adds `messages: [{"role": "user", ...}]` -> routes to `llm-call`
2. **llm-call** (pod #37 out of 100): Calls Gemini with messages + google_search tool -> returns `{"tool_calls": [{"name": "google_search", "args": {"query": "capital of France"}}]}`
3. **dispatch-router**: Sees `tool_calls` -> routes to `google-search`
4. **google-search** (pod #12): Executes search -> returns `{"result": "Paris is the capital of France..."}`
5. **collect-router**: Appends tool result to messages -> routes back to `llm-call`
6. **llm-call** (pod #85 -- different pod! stateless!): Calls Gemini with updated messages -> returns `{"text": "The capital of France is Paris...", "tool_calls": []}` (no more tool calls)
7. **dispatch-router**: No tool_calls -> routes to `reviser-llm-call`
8. **reviser-llm-call** (pod #3): Calls Gemini with critique + query -> returns revised answer
9. -> `happy-end`

- No sticky sessions needed
- Every actor is stateless -- any pod can process any message
- Full conversation context travels in payload
- The compiler generated the router network from the async function

### What About Streaming?

During step 2 and 8 (LLM calls), the actors can **yield partial text deltas** via the streaming side-channel:

```python
async def llm_call(state: dict) -> AsyncGenerator[dict, None]:
    messages = state["messages"]

    async for chunk in gemini.generate_content_async(messages, stream=True):
        if chunk.text:
            yield {"type": "text_delta", "delta": chunk.text}  # -> HTTP -> gateway -> user
        if chunk.tool_calls:
            yield {"type": "result", "tool_calls": chunk.tool_calls}  # -> queue -> dispatch-router
            return

    yield {"type": "result", "text": full_response}  # -> queue -> next actor
```

The sidecar classifies events:
- `type: "text_delta"` -> HTTP side-channel -> gateway -> SSE to user
- `type: "result"` -> queue -> next actor (the last yield, per Option B convention)

### The Two Compilation Levels

There are **two distinct levels** the compiler handles:

**Level 1: Orchestration compilation** (SequentialAgent -> flow)

```python
# ADK declarative:
SequentialAgent(sub_agents=[critic, reviser])

# Asya async function:
async def llm_auditor(state):
    state = await critic(state)
    state = await reviser(state)
    return state

# Compiled: linear route [critic, reviser]
```

This is what the **current flow compiler already does** (sequential, conditional, fan-out).

**Level 2: Agent decomposition** (LlmAgent with tools -> ReAct loop actors)

```python
# ADK declarative:
Agent(model="gemini", tools=[google_search])

# Asya async function:
async def critic(state) -> AsyncGenerator:
    while True:
        response = await llm_call(state)     # split
        if response.tool_calls:
            result = await tool(state)        # split
        else:
            yield result                      # done
            return

# Compiled: llm-call -> dispatch-router -> [tools] -> collect-router -> (loop)
```

This is **new** -- the flow compiler doesn't handle `while` loops, `await` split points, or async generators today.

### What the Compiler Needs to Learn

To support Level 2, the flow compiler needs three new capabilities:

1. **`await` as split point**: Each `await expr` becomes a message send + actor boundary
2. **`while True` as loop**: The compiler generates a router that loops back to a previous actor
3. **`AsyncGenerator` yield convention**: Intermediate yields -> streaming side-channel, last yield -> control event -> queue

These map directly to what ADK's internal orchestration does -- but transformed from in-process generator nesting to distributed message passing.

### Core Transformation: CPS (Continuation-Passing Style)

Each `await` in the user's code becomes a continuation boundary. The compiler transforms:

```python
x = await A()
y = await B(x)
```

Into:

```
Actor-1: call A, put result in payload, route to Actor-2
Actor-2: read A's result from payload, call B, route to next
```

This is exactly what Go does with goroutines at the runtime level (stack splitting at function calls), and what JavaScript does with `async/await` transpilation to `.then()` chains. The Asya compiler does the same thing, but across network boundaries.

### What's Next?

The prototype validates against the real ADK LLM Auditor. The compiler would need to:

1. Parse the async function AST (extend current `parser.py`)
2. Recognize `await` calls as split points (new)
3. Recognize `while True` as loop constructs (new -- currently "Loops not yet supported")
4. Recognize `yield` as event emission with last-yield = control (new)
5. Generate the router network (extend current `code_generator.py`)
