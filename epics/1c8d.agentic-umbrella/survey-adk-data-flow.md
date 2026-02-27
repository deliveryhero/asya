# Google ADK Data Flow Survey

> **Purpose**: Deep-dive into Google ADK's event system, data flow, agent composition,
> and tool lifecycle. Identifies every pattern Asya must support to be fully agentic.
>
> **Date**: 2026-02-27
> **Source**: [google/adk-python](https://github.com/google/adk-python) (main branch)
> **Companion**: `survey-agentic-frameworks.md` (broad 14-framework comparison)


## What this document covers:

The survey is structured as a reference document with 8 sections:

1. **Core architecture** -- the yield/pause/resume event loop with ASCII flow diagram
2. **Event types** -- complete field listings for Event (26 fields), EventActions (11 fields), and Content.Part (7 part types), plus
classification logic and is_final_response() decision tree
3. **ReAct loop** -- BaseLlmFlow.run_async() while-true mechanics, preprocess/LLM/postprocess stages, 6 termination conditions, and tool
result feedback cycle
4. **Tool system** -- class hierarchy, FunctionTool schema generation, complete 8-step execution pipeline, parallel asyncio.gather(),
ToolContext API, long-running tools, confirmation, streaming tools, before/after callbacks
5. **Agent composition** -- 5 patterns (Sequential, Parallel, Loop, AgentTool, Transfer) with exact event propagation semantics and a
cross-reference matrix
6. **State management** -- delta-tracked State object, scope prefixes, output_key enrichment, context sharing rules per composition type
7. **8 end-to-end examples** -- simple tool call, streaming+tool, parallel tools, sequential pipeline, AgentTool, LoopAgent+escalation,
long-running pause/resume, agent transfer
8. **Asya gap analysis** -- 18 patterns mapped with status, 4 critical gaps identified

The 4 critical gaps for Asya:
- Free variable serialization across actor boundaries (epic 1irj)
- Dynamic routing (ADK's transfer_to_agent vs Asya's static conditional routers)
- Parallel actor calls in Flow DSL (ADK's asyncio.gather for multi-tool)
- Escalation as first-class action (ADK's escalate vs Asya's payload-based break)

---

## 1. Core Architecture: The Event Loop

ADK's runtime is built on a **yield/pause/resume cycle** using Python's `AsyncGenerator`.
Every agent is an async generator that yields `Event` objects. The Runner consumes these
events, applies side effects (persistence, state commits), and forwards them upstream
to the application/UI.

```
User Query
    |
    v
Runner.run_async()                    <-- async generator
    |
    v
Agent.run_async(ctx)                  <-- async generator
    |
    v
BaseLlmFlow.run_async(ctx)           <-- ReAct loop (while True)
    |
    +-- _run_one_step_async(ctx)
    |       |-- _preprocess_async     <-- build LLM request
    |       |-- _call_llm_async       <-- invoke LLM provider
    |       |     +-- yield partial Events (streaming tokens)
    |       |     +-- yield final LLM response Event
    |       |-- _postprocess_async    <-- check for function calls
    |       |     +-- If function calls:
    |       |     |     handle_function_calls_async()   <-- parallel via asyncio.gather
    |       |     |     yield function response Event
    |       |     +-- If transfer_to_agent:
    |       |           run target agent, yield its events
    |       +-- yield events
    |
    +-- check: is_final_response()? --> break
    |   else: loop again (tool result now in session history)
    |
    v
Runner processes each event:
    |-- partial? --> forward to UI, skip persistence
    |-- non-partial? --> session_service.append_event()
    |                    apply state_delta, artifact_delta
    +-- yield event upstream to application
```

**Source**: [runners.py](https://github.com/google/adk-python/blob/main/src/google/adk/runners.py),
[base_llm_flow.py](https://github.com/google/adk-python/blob/main/src/google/adk/flows/llm_flows/base_llm_flow.py)

---

## 2. Event Types and Classification

### 2.1 Class Hierarchy

```
BaseModel (pydantic)
  +-- LlmResponse
        +-- Event
```

- [LlmResponse](https://github.com/google/adk-python/blob/main/src/google/adk/models/llm_response.py) --
  LLM provider response wrapper (content, partial flag, usage metadata, errors)
- [Event](https://github.com/google/adk-python/blob/main/src/google/adk/events/event.py) --
  ADK-level event with agent metadata, actions, branching
- [EventActions](https://github.com/google/adk-python/blob/main/src/google/adk/events/event_actions.py) --
  side-effect container (state deltas, transfers, escalation, auth)

### 2.2 Event Fields (Complete)

**From LlmResponse (inherited)**:

| Field | Type | Purpose |
|---|---|---|
| `content` | `Optional[types.Content]` | Text, function calls, function responses |
| `partial` | `Optional[bool]` | `True` for streaming chunks |
| `turn_complete` | `Optional[bool]` | Model finished its entire turn |
| `finish_reason` | `Optional[types.FinishReason]` | Why the model stopped |
| `error_code` | `Optional[str]` | Error code if LLM errored |
| `error_message` | `Optional[str]` | Error message if LLM errored |
| `interrupted` | `Optional[bool]` | LLM interrupted (bidi streaming) |
| `usage_metadata` | `Optional[...UsageMetadata]` | Token counts |
| `model_version` | `Optional[str]` | Model version used |
| `grounding_metadata` | `Optional[...GroundingMetadata]` | Search grounding |
| `custom_metadata` | `Optional[dict[str, Any]]` | Arbitrary JSON metadata |
| `input_transcription` | `Optional[types.Transcription]` | Audio input transcription |
| `output_transcription` | `Optional[types.Transcription]` | Audio output transcription |
| `avg_logprobs` | `Optional[float]` | Average log probability |
| `logprobs_result` | `Optional[types.LogprobsResult]` | Detailed log probabilities |
| `cache_metadata` | `Optional[CacheMetadata]` | Context cache info |
| `citation_metadata` | `Optional[types.CitationMetadata]` | Citations |
| `interaction_id` | `Optional[str]` | Interactions API ID |

**Event-specific fields**:

| Field | Type | Default | Purpose |
|---|---|---|---|
| `id` | `str` | UUID | Unique event identifier |
| `invocation_id` | `str` | `''` | Correlates all events in one user interaction |
| `author` | `str` | **required** | `"user"` or agent name (e.g. `"WeatherAgent"`) |
| `actions` | `EventActions` | `EventActions()` | Side effects (state, transfers, auth) |
| `long_running_tool_ids` | `Optional[set[str]]` | `None` | IDs of long-running function calls |
| `branch` | `Optional[str]` | `None` | Hierarchical path for parallel execution |
| `timestamp` | `float` | `now()` | Creation time |

### 2.3 EventActions Fields (Complete)

| Field | Type | Default | Purpose |
|---|---|---|---|
| `state_delta` | `dict[str, object]` | `{}` | State changes to persist |
| `artifact_delta` | `dict[str, int]` | `{}` | Artifact version updates |
| `transfer_to_agent` | `Optional[str]` | `None` | Route control to named agent |
| `escalate` | `Optional[bool]` | `None` | Terminate loop execution |
| `skip_summarization` | `Optional[bool]` | `None` | Return tool result directly |
| `end_of_agent` | `Optional[bool]` | `None` | Agent finished its run |
| `agent_state` | `Optional[dict[str, Any]]` | `None` | Checkpoint for resume |
| `requested_auth_configs` | `dict[str, AuthConfig]` | `{}` | Auth configs by call ID |
| `requested_tool_confirmations` | `dict[str, ToolConfirmation]` | `{}` | Confirmations by call ID |
| `compaction` | `Optional[EventCompaction]` | `None` | Event history compaction |
| `rewind_before_invocation_id` | `Optional[str]` | `None` | Invocation ID to rewind to |

### 2.4 Content Structure

`types.Content` (from Google GenAI SDK):

```python
class Content:
    role: Optional[str]   # "user" or "model"
    parts: list[Part]     # heterogeneous content parts
```

Each `Part` contains exactly one of:

| Part Field | Type | Meaning |
|---|---|---|
| `text` | `str` | Plain text |
| `inline_data` | `Blob` | Binary data (images, audio) |
| `function_call` | `FunctionCall` | Tool invocation request from LLM |
| `function_response` | `FunctionResponse` | Tool result sent back to LLM |
| `executable_code` | `ExecutableCode` | Code to execute |
| `code_execution_result` | `CodeExecutionResult` | Code output |
| `thought` | `bool` | Thinking/reasoning content |

**FunctionCall**:
```python
class FunctionCall:
    name: str           # tool/function name
    args: dict[str, Any] # arguments as key-value pairs
    id: Optional[str]   # links request to response
```

**FunctionResponse**:
```python
class FunctionResponse:
    name: str               # tool/function name (matches FunctionCall.name)
    response: dict[str, Any] # result dictionary
    id: Optional[str]       # links back to FunctionCall.id
```

### 2.5 Event Classification

Events are classified by inspecting fields, not by a type enum:

```python
def classify_event(event: Event) -> str:
    if event.author == "user":
        return "USER_INPUT"

    if event.long_running_tool_ids:
        return "LONG_RUNNING_TOOL_CALL"

    if event.get_function_calls():
        return "TOOL_CALL"

    if event.get_function_responses():
        if event.actions.skip_summarization:
            return "TOOL_RESPONSE_FINAL"   # returned directly to user
        return "TOOL_RESPONSE"             # will be summarized by LLM

    if event.partial:
        return "STREAMING_PARTIAL"

    if event.actions.transfer_to_agent:
        return "AGENT_TRANSFER"

    if event.actions.escalate:
        return "ESCALATION"

    if event.actions.state_delta or event.actions.artifact_delta:
        if not event.content:
            return "STATE_UPDATE"

    if event.has_trailing_code_execution_result():
        return "CODE_EXECUTION_RESULT"

    if event.content and event.content.parts:
        return "TEXT_RESPONSE"

    return "UNKNOWN"
```

### 2.6 is_final_response() Logic

```python
def is_final_response(self) -> bool:
    # Short-circuit: skip_summarization or long-running tools
    if self.actions.skip_summarization or self.long_running_tool_ids:
        return True
    return (
        not self.get_function_calls()                # no pending tool calls
        and not self.get_function_responses()         # not a tool result
        and not self.partial                          # not a streaming chunk
        and not self.has_trailing_code_execution_result()  # no code output pending
    )
```

**Decision tree**:
1. `skip_summarization` or `long_running_tool_ids` --> **final** (done immediately)
2. Has function calls --> **not final** (tools must execute, then loop)
3. Has function responses --> **not final** (LLM must process tool results)
4. Is partial --> **not final** (streaming in progress)
5. Has code execution result --> **not final** (LLM must process code output)
6. Otherwise --> **final** (text-only response, done)

### 2.7 Partial (Streaming) Events

| Property | Partial (`partial=True`) | Final (`partial=False/None`) |
|---|---|---|
| Persistence | NOT persisted to session | Persisted via `append_event()` |
| State deltas | NOT applied | Applied to session state |
| Tool execution | SKIPPED even if contains function calls | Executed normally |
| Forwarding | Forwarded to UI for real-time display | Forwarded to UI |
| LLM history | NOT visible in future LLM turns | Visible in conversation history |
| `is_final_response()` | Always `False` | Depends on content |

**Source**: [runners.py](https://github.com/google/adk-python/blob/main/src/google/adk/runners.py) --
persistence check:
```python
if event.partial is not True:
    await self.session_service.append_event(session=session, event=event)
```

---

## 3. The ReAct Loop

### 3.1 BaseLlmFlow.run_async() -- The While Loop

```python
async def run_async(self, invocation_context: InvocationContext):
    while True:
        last_event = None
        async with Aclosing(self._run_one_step_async(invocation_context)) as agen:
            async for event in agen:
                last_event = event
                yield event
        if not last_event or last_event.is_final_response() or last_event.partial:
            break
```

**One "step" of ReAct** (`_run_one_step_async`):

1. **Preprocess** (`_preprocess_async`):
   - Run `request_processors` (instructions, content prep, auth, caching)
   - Resolve toolset authentication
   - Build `llm_request.tools_dict` from agent tools
   - Can yield auth request events and abort via `end_invocation=True`

2. **Call LLM** (`_call_llm_async`):
   - Run `before_model_callback` -- can short-circuit (return response without calling LLM)
   - `llm.generate_content_async(llm_request, stream=True/False)`
   - Run `after_model_callback` -- can alter response
   - Yield `LlmResponse` objects (multiple if streaming)

3. **Postprocess** (`_postprocess_async`):
   - Run `response_processors`
   - Finalize model response into Event
   - If function calls AND NOT partial:
     - `handle_function_calls_async()` -- execute tools (parallel)
     - Yield function response event
     - If `transfer_to_agent` action: recursively run target agent

**Source**: [base_llm_flow.py](https://github.com/google/adk-python/blob/main/src/google/adk/flows/llm_flows/base_llm_flow.py)

### 3.2 Loop Termination Conditions

| Condition | Where Checked | Effect |
|---|---|---|
| No events produced | `run_async` | Break (empty step) |
| `is_final_response()` | `run_async` | Break (LLM gave text answer) |
| `partial` on last event | `run_async` | Break with warning |
| `end_invocation=True` | `_run_one_step_async` | Return (auth/callback abort) |
| `should_pause_invocation()` | `_run_one_step_async` | Return (long-running tool pause) |
| LLM call count exceeded | `_call_llm_async` | Exception (max iterations guard) |

### 3.3 Tool Result Feedback

Tool results feed back to the LLM through **session history**:

```
1. LLM returns FunctionCall(name="search", args={"q": "..."})
       |
2. handle_function_calls_async() executes tool
       |
3. Result packaged as Event(content=Content(role="user",
       parts=[Part(function_response=FunctionResponse(...))]))
       |
4. Event yielded upstream --> Runner persists to session
       |
5. ReAct loop continues (is_final_response() was False)
       |
6. Next _run_one_step_async() reads session history
       |
7. LLM sees: [user msg, model response with tool call, tool result]
       |
8. LLM generates next response (text or more tool calls)
```

---

## 4. Tool System

### 4.1 Tool Class Hierarchy

```
BaseTool (ABC)
  +-- FunctionTool               <-- wraps Python functions
  |     +-- LongRunningFunctionTool
  +-- AgentTool                  <-- wraps a sub-agent as a tool
  +-- TransferToAgentTool        <-- dynamic agent routing
  +-- GoogleSearchTool           <-- built-in Google Search
  +-- CodeExecutionTool          <-- built-in code execution
  +-- McpTool                    <-- MCP protocol tools
  +-- RestApiTool                <-- REST API wrapper
```

**Source**: [base_tool.py](https://github.com/google/adk-python/blob/main/src/google/adk/tools/base_tool.py),
[function_tool.py](https://github.com/google/adk-python/blob/main/src/google/adk/tools/function_tool.py)

### 4.2 FunctionTool: Python Functions as Tools

```python
class FunctionTool(BaseTool):
    def __init__(self, func, *, require_confirmation=False):
        name = func.__name__
        doc = inspect.cleandoc(func.__doc__)
        super().__init__(name=name, description=doc)
        self.func = func
        self._ignore_params = ['tool_context', 'input_stream']
```

**Schema generation** (`_get_declaration`):
- `inspect.signature()` extracts parameters
- `typing.get_type_hints()` resolves forward references
- `tool_context` and `input_stream` params are hidden from LLM
- Python types map to JSON Schema: `str` --> STRING, `int` --> INTEGER, etc.
- `Optional[T]` gets `nullable=True`
- Pydantic models auto-convert via `model_validate()`

**Execution** (`run_async`):
1. `_preprocess_args()` -- convert JSON dicts to Pydantic models
2. Inject `tool_context` if function accepts it
3. Validate mandatory args (return error dict if missing)
4. Check confirmation requirement
5. `_invoke_callable()` -- handles both sync and async functions:
   ```python
   if inspect.iscoroutinefunction(target):
       return await target(**args_to_call)
   else:
       return target(**args_to_call)
   ```

### 4.3 Tool Execution Pipeline (Complete)

**Source**: [functions.py](https://github.com/google/adk-python/blob/main/src/google/adk/flows/llm_flows/functions.py)

```
LLM returns Content with FunctionCall parts
    |
    v
handle_function_calls_async()
    |
    v
For EACH FunctionCall (PARALLEL via asyncio.gather):
    |
    +-- 1. _create_tool_context()
    |       - InvocationContext, function_call_id, tool_confirmation
    |
    +-- 2. _get_tool(function_call.name, tools_dict)
    |
    +-- 3. Plugin before_tool_callback
    |       -> non-None return? SKIP tool, use as result
    |
    +-- 4. Agent before_tool_callbacks (first non-None wins)
    |       -> non-None return? SKIP tool, use as result
    |
    +-- 5. tool.run_async(args=..., tool_context=...)
    |       - Pydantic conversion, context injection, confirmation check
    |       - On exception: on_tool_error_callbacks
    |
    +-- 6. Plugin after_tool_callback
    |       -> non-None return? REPLACE result
    |
    +-- 7. Agent after_tool_callbacks (first non-None wins)
    |       -> non-None return? REPLACE result
    |
    +-- 8. __build_response_event()
            - Non-dict result wrapped in {'result': value}
            - Part.from_function_response(name=tool.name, response=result)
            - FunctionResponse.id = function_call_id
            - Content(role='user', parts=[response_part])
            - Event(actions=tool_context.actions)
    |
    v
merge_parallel_function_response_events()
    - All response parts combined into single Content
    - All EventActions deep-merged (state_delta, artifact_delta, etc.)
    |
    v
Merged Event yielded to agent loop
    - Persisted to session history
    - State deltas applied
    - Content sent to LLM in next turn
```

### 4.4 Parallel Tool Execution

When the LLM makes multiple function calls in one response:

```python
# functions.py
tasks = [
    asyncio.create_task(
        _execute_single_function_call_async(
            invocation_context, function_call, tools_dict, agent, ...
        )
    )
    for function_call in filtered_calls
]
function_response_events = await asyncio.gather(*tasks)
merged_event = merge_parallel_function_response_events(function_response_events)
```

All tools run concurrently. Results are merged into a single event with combined parts
and deep-merged action dictionaries.

### 4.5 ToolContext (= Context)

**Source**: [context.py](https://github.com/google/adk-python/blob/main/src/google/adk/agents/context.py)

`ToolContext` is an alias for `Context`. The `Context` class provides:

**State access** (mutable, delta-tracked):
```python
tool_context.state["key"] = "value"   # writes to session AND records delta
count = tool_context.state.get("call_count", 0)
```

State key prefixes (convention, not enforced):
- No prefix: session-scoped, persisted
- `app:` -- shared across all users/sessions
- `user:` -- per-user, cross-session
- `temp:` -- discarded after invocation

**Artifact methods**:
- `save_artifact(filename, artifact) -> int` (returns version)
- `load_artifact(filename, version=None) -> Part | None`
- `list_artifacts() -> list[str]`

**Flow control** via `tool_context.actions`:
- `actions.transfer_to_agent = "other_agent"` -- hand off
- `actions.escalate = True` -- break loop
- `actions.skip_summarization = True` -- return tool result directly to user

**Auth methods**:
- `request_credential(auth_config)` -- trigger OAuth/auth flow
- `load_credential(auth_config)` -- retrieve stored credentials
- `get_auth_response(auth_config)` -- get auth response from client

**Confirmation**:
- `request_confirmation(hint=..., payload=...)` -- ask user to approve

**Memory**:
- `search_memory(query) -> SearchMemoryResponse`
- `add_session_to_memory()`

### 4.6 Long-Running Tools

**Source**: [long_running_tool.py](https://github.com/google/adk-python/blob/main/src/google/adk/tools/long_running_tool.py)

```python
class LongRunningFunctionTool(FunctionTool):
    def __init__(self, func):
        super().__init__(func)
        self.is_long_running = True
```

Flow:
1. Tool returns immediately with intermediate status (e.g. `{"status": "pending"}`)
2. `is_final_response()` returns `True` when `long_running_tool_ids` is set
3. Agent invocation pauses (`should_pause_invocation`)
4. Client polls/waits for actual result asynchronously
5. Client sends `FunctionResponse` with matching `function_call_id`
6. Framework resumes invocation, LLM sees the completed result

### 4.7 Tool Confirmation

**Source**: [tool_confirmation.py](https://github.com/google/adk-python/blob/main/src/google/adk/tools/tool_confirmation.py)

```python
class ToolConfirmation(BaseModel):
    hint: str = ""
    confirmed: bool = False
    payload: Optional[Any] = None
```

Flow:
1. `require_confirmation=True` on FunctionTool (static or callable)
2. First call: `request_confirmation()` stores in `EventActions.requested_tool_confirmations`
3. Returns `{'error': 'This tool call requires confirmation.'}` with `skip_summarization=True`
4. Client presents confirmation to user
5. Re-invocation with `ToolConfirmation(confirmed=True/False)`
6. If confirmed: tool executes normally. If rejected: returns error.

### 4.8 Streaming Tools (Live Mode)

```python
# function_tool.py -- _call_live()
async def _call_live(self, *, args, tool_context, invocation_context):
    if self.name in invocation_context.active_streaming_tools:
        args_to_call['input_stream'] = (
            invocation_context.active_streaming_tools[self.name].stream
        )
    async with Aclosing(self.func(**args_to_call)) as agen:
        async for item in agen:
            yield item
```

Streaming tools are async generators that accept an `input_stream` parameter
and `yield` results incrementally. Only available in Live API mode (bidirectional
audio/video streaming).

### 4.9 Callbacks

**Before/after model** (intercept LLM calls):
```python
LlmAgent(
    before_model_callback=fn,   # (CallbackContext, LlmRequest) -> Optional[LlmResponse]
    after_model_callback=fn,    # (CallbackContext, LlmResponse) -> Optional[LlmResponse]
    on_model_error_callback=fn, # (CallbackContext, error) -> Optional[LlmResponse]
)
```
Return `None` to continue normally. Return `LlmResponse` to skip LLM / replace response.

**Before/after tool** (intercept tool execution):
```python
LlmAgent(
    before_tool_callback=fn,    # (BaseTool, args, ToolContext) -> Optional[dict]
    after_tool_callback=fn,     # (BaseTool, args, ToolContext, response) -> Optional[dict]
    on_tool_error_callback=fn,  # (BaseTool, args, ToolContext, error) -> Optional[dict]
)
```
Return `None` to continue normally. Return `dict` to skip tool / replace result.

**Priority**: Plugin callbacks run first, then agent-level callbacks. First non-None wins.

---

## 5. Agent Composition Patterns

### 5.1 Composition Types Overview

| Type | LLM? | Sub-Agents | Event Propagation | State Sharing |
|---|---|---|---|---|
| **SequentialAgent** | No | Ordered list | All yielded upstream | Shared session |
| **ParallelAgent** | No | Concurrent set | All yielded upstream (interleaved) | Shared session (race risk) |
| **LoopAgent** | No | Iterated list | All yielded upstream (per iteration) | Shared session |
| **LlmAgent** (transfer) | Yes | Dynamic routing | All yielded upstream | Shared session |
| **AgentTool** | Caller has LLM | Encapsulated | ABSORBED -- only final text returns | Copied in, deltas forwarded |

### 5.2 SequentialAgent

**Source**: [sequential_agent.py](https://github.com/google/adk-python/blob/main/src/google/adk/agents/sequential_agent.py)

```python
async def _run_async_impl(self, ctx: InvocationContext):
    for i in range(start_index, len(self.sub_agents)):
        sub_agent = self.sub_agents[i]
        async with Aclosing(sub_agent.run_async(ctx)) as agen:
            async for event in agen:
                yield event                          # all events propagate
                if ctx.should_pause_invocation(event):
                    pause_invocation = True
        if pause_invocation:
            return
```

- Same `ctx` passed to each sub-agent serially
- All events yielded directly upstream
- Data flows via `output_key` on one agent --> `{variable}` template in next agent's instructions
- Pause/resume via `SequentialAgentState.current_sub_agent`

### 5.3 ParallelAgent

**Source**: [parallel_agent.py](https://github.com/google/adk-python/blob/main/src/google/adk/agents/parallel_agent.py)

Each sub-agent gets a **branched context**:
```python
invocation_context = invocation_context.model_copy()
branch_suffix = f'{agent.name}.{sub_agent.name}'
invocation_context.branch = (
    f'{invocation_context.branch}.{branch_suffix}'
    if invocation_context.branch
    else branch_suffix
)
```

Events merged via `asyncio.Queue` with backpressure:
```python
async def _merge_agent_run(agent_runs):
    queue = asyncio.Queue()

    async def process_an_agent(events_for_one_agent):
        async for event in events_for_one_agent:
            resume_signal = asyncio.Event()
            await queue.put((event, resume_signal))
            await resume_signal.wait()               # backpressure

    async with asyncio.TaskGroup() as tg:
        for events in agent_runs:
            tg.create_task(process_an_agent(events))
        while sentinel_count < len(agent_runs):
            event, resume_signal = await queue.get()
            yield event
            resume_signal.set()
```

- All events from all branches yielded upstream (interleaved)
- `session.state` shared across branches (same Session object, race risk)
- Conversation history isolated per branch via `branch` tag on events

### 5.4 LoopAgent

**Source**: [loop_agent.py](https://github.com/google/adk-python/blob/main/src/google/adk/agents/loop_agent.py)

```python
async def _run_async_impl(self, ctx: InvocationContext):
    while (not self.max_iterations or times_looped < self.max_iterations)
          and not (should_exit or pause_invocation):
        for sub_agent in self.sub_agents:
            async for event in sub_agent.run_async(ctx):
                yield event
                if event.actions.escalate:
                    should_exit = True
                if ctx.should_pause_invocation(event):
                    pause_invocation = True
            if should_exit or pause_invocation:
                break
        times_looped += 1
        ctx.reset_sub_agent_states(self.name)
```

**Termination**:
- `max_iterations` reached
- Any sub-agent sets `event.actions.escalate = True` (e.g. via a tool:
  `tool_context.actions.escalate = True`)

### 5.5 LLM-Driven Transfer (transfer_to_agent)

**Source**: [auto_flow.py](https://github.com/google/adk-python/blob/main/src/google/adk/flows/llm_flows/auto_flow.py),
[transfer_to_agent_tool.py](https://github.com/google/adk-python/blob/main/src/google/adk/tools/transfer_to_agent_tool.py)

AutoFlow extends SingleFlow by adding a `transfer_to_agent` tool:
```python
def transfer_to_agent(agent_name: str, tool_context: ToolContext):
    tool_context.actions.transfer_to_agent = agent_name
```

The `agent_name` parameter is constrained to an enum of valid targets
(sub-agents, parent, peers based on `disallow_transfer_to_parent`/`disallow_transfer_to_peers`).

Transfer directions:
- Parent --> sub-agent: always allowed
- Sub-agent --> parent: allowed unless `disallow_transfer_to_parent = True`
- Sub-agent --> peer: allowed unless `disallow_transfer_to_peers = True`

On the next user message, `Runner._find_agent_to_run()` routes to the target agent.

### 5.6 AgentTool (Agent-as-Tool)

**Source**: [agent_tool.py](https://github.com/google/adk-python/blob/main/src/google/adk/tools/agent_tool.py)

The most distinct composition mode. Creates a **complete isolation boundary**:

```python
async def run_async(self, *, args, tool_context):
    # 1. New Runner with own session service
    runner = Runner(
        agent=self.agent,
        session_service=InMemorySessionService(),
        artifact_service=ForwardingArtifactService(tool_context),
        ...
    )

    # 2. Copy parent state (excluding _adk* keys) into child session
    state_dict = {
        k: v for k, v in tool_context.state.to_dict().items()
        if not k.startswith('_adk')
    }
    session = await runner.session_service.create_session(state=state_dict)

    # 3. Run agent, forward state deltas, capture final content
    async for event in runner.run_async(session_id=session.id, new_message=content):
        if event.actions.state_delta:
            tool_context.state.update(event.actions.state_delta)   # forward deltas
        if event.content:
            last_content = event.content                           # capture final

    # 4. Return only the final text (thought parts filtered)
    merged_text = '\n'.join(
        p.text for p in last_content.parts if p.text and not p.thought
    )
    return merged_text
```

| Aspect | Behavior |
|---|---|
| Events from child | **ABSORBED** -- parent never sees individual events |
| State deltas | **FORWARDED** via `tool_context.state.update()` |
| Artifacts | **FORWARDED** via `ForwardingArtifactService` |
| Conversation history | **ISOLATED** (new `InMemorySessionService`) |
| Thinking/reasoning | **FILTERED** (`p.thought` parts excluded from merged text) |

### 5.7 Event Propagation Matrix

| Source | Sequential | Parallel | Loop | AgentTool | Transfer |
|---|---|---|---|---|---|
| Sub-agent events | All upstream | All upstream (interleaved) | All upstream (per iteration) | **Absorbed** | All upstream |
| State deltas | Shared directly | Shared (race risk) | Shared across iterations | Forwarded | Shared |
| Conversation history | Shared | Isolated per branch | Shared (reset between iterations) | Isolated | Shared |
| `escalate` | Ignored | Ignored | **Terminates loop** | N/A | N/A |
| `should_pause` | Stops at current | Stops all branches | Stops loop | N/A | Handled by flow |
| `transfer_to_agent` | N/A | N/A | N/A | N/A | Handled by Runner |

---

## 6. State Management

### 6.1 State Object

**Source**: [state.py](https://github.com/google/adk-python/blob/main/src/google/adk/sessions/state.py)

```python
class State:
    APP_PREFIX = "app:"
    USER_PREFIX = "user:"
    TEMP_PREFIX = "temp:"

    def __init__(self, value: dict[str, Any], delta: dict[str, Any]):
        self._value = value     # actual session state
        self._delta = delta     # pending changes (ref to EventActions.state_delta)

    def __setitem__(self, key, value):
        self._value[key] = value  # update session immediately
        self._delta[key] = value  # record in delta for event propagation
```

Every mutation simultaneously updates the live session state AND records the change
in `EventActions.state_delta`. This delta is attached to the response event and
persisted by the Runner.

### 6.2 State Scope Conventions

| Prefix | Scope | Persistence |
|---|---|---|
| (none) | Session | Within session lifetime |
| `app:` | Application | Across all users/sessions |
| `user:` | User | Across sessions for one user |
| `temp:` | Invocation | Discarded after invocation |

### 6.3 output_key -- State Enrichment

When `output_key` is set on an LlmAgent, the final text response is saved to state:

```python
# llm_agent.py
def __maybe_save_output_to_state(self, event):
    if self.output_key and event.is_final_response() and event.content:
        result = ''.join(
            part.text for part in event.content.parts if part.text and not part.thought
        )
        event.actions.state_delta[self.output_key] = result
```

This enables pipeline patterns:
```python
analyzer = LlmAgent(name="Analyzer", output_key="analysis", ...)
writer   = LlmAgent(name="Writer",   instruction="Based on: {analysis}", ...)
pipeline = SequentialAgent(sub_agents=[analyzer, writer])
```

### 6.4 InvocationContext Sharing

| Composition | Context | State | History |
|---|---|---|---|
| SequentialAgent | Same `ctx` | Shared (same Session) | Shared |
| ParallelAgent | `ctx.model_copy()` per branch | Shared (same Session, race risk) | Isolated per branch |
| LoopAgent | Same `ctx` | Shared, sub-agent states reset | Shared |
| AgentTool | New Runner + Session | Copied in, deltas forwarded | Isolated |
| LLM transfer | Same `ctx` | Shared | Shared |

---

## 7. Complete Event Data Flow Examples

### 7.1 Simple Tool Call

```
User: "What's the weather in Tokyo?"

1. Runner.run_async() appends user message to session
2. Agent.run_async() --> BaseLlmFlow.run_async() --> while True:
3. _run_one_step_async():
   3a. _preprocess_async: build LLM request with tools=[get_weather]
   3b. _call_llm_async: LLM returns:
       Event(author="WeatherAgent", content=Content(role="model", parts=[
           Part(function_call=FunctionCall(
               name="get_weather", args={"city": "Tokyo"}, id="fc_001"
           ))
       ]))
   3c. _postprocess_async: detects function call
       --> handle_function_calls_async():
           - _execute_single_function_call_async("get_weather", {"city": "Tokyo"})
           - tool returns {"temp": "22C", "condition": "Sunny"}
           - __build_response_event():
             Event(author="WeatherAgent", content=Content(role="user", parts=[
                 Part(function_response=FunctionResponse(
                     name="get_weather",
                     response={"temp": "22C", "condition": "Sunny"},
                     id="fc_001"
                 ))
             ]))
   3d. yield function_call Event (persisted, not final)
   3e. yield function_response Event (persisted, not final)
4. Loop continues (is_final_response() = False for function response)
5. _run_one_step_async() again:
   5a. LLM sees: [user msg, tool call, tool result] in history
   5b. LLM returns:
       Event(author="WeatherAgent", content=Content(role="model", parts=[
           Part(text="The weather in Tokyo is 22C and sunny.")
       ]))
   5c. is_final_response() = True (text only, no tool calls)
6. Loop breaks. Done.
```

### 7.2 Streaming with Tool Call

```
User: "Write a poem about rain, then check the weather"

1-3. Same as above...
3b. _call_llm_async (streaming mode):
    yield Event(partial=True, content=Part(text="Here's a"))      # not persisted
    yield Event(partial=True, content=Part(text="Here's a poem"))  # not persisted
    yield Event(partial=True, content=Part(text="Here's a poem about rain:\n"))
    ...
    yield Event(partial=False, content=Content(parts=[
        Part(text="Here's a poem about rain:\nRaindrops fall..."),
        Part(function_call=FunctionCall(name="get_weather", ...))
    ]))
    --> partial events forwarded to UI but NOT persisted
    --> final event: has function call, so NOT final
    --> tool execution proceeds as in 7.1
```

### 7.3 Parallel Tool Execution

```
LLM returns Content with TWO function calls:

Event(content=Content(role="model", parts=[
    Part(function_call=FunctionCall(name="get_weather", args={"city": "Tokyo"}, id="fc_001")),
    Part(function_call=FunctionCall(name="get_weather", args={"city": "Paris"}, id="fc_002")),
]))

handle_function_calls_async():
  tasks = [
      asyncio.create_task(execute("get_weather", {"city": "Tokyo"}, id="fc_001")),
      asyncio.create_task(execute("get_weather", {"city": "Paris"}, id="fc_002")),
  ]
  results = await asyncio.gather(*tasks)
  # Two response events, merged into one:
  Event(content=Content(role="user", parts=[
      Part(function_response=FunctionResponse(name="get_weather", response={...}, id="fc_001")),
      Part(function_response=FunctionResponse(name="get_weather", response={...}, id="fc_002")),
  ]))
```

### 7.4 SequentialAgent with output_key

```
pipeline = SequentialAgent(sub_agents=[
    LlmAgent(name="Researcher", output_key="research", instruction="Research {topic}"),
    LlmAgent(name="Writer", instruction="Write article based on: {research}"),
])

1. Researcher runs:
   - LLM generates research text
   - __maybe_save_output_to_state: state_delta["research"] = "Research findings..."
   - Event(actions=EventActions(state_delta={"research": "Research findings..."}))
   - Runner persists event, applies state delta

2. Writer runs:
   - Instruction template resolves: "Write article based on: Research findings..."
   - LLM generates article
   - Event with final text

All events from both agents yielded upstream to caller.
```

### 7.5 AgentTool (Sub-Agent as Tool)

```
parent_agent = LlmAgent(
    name="Orchestrator",
    tools=[AgentTool(agent=ResearchAgent(...))]
)

1. Orchestrator LLM calls: FunctionCall(name="ResearchAgent", args={"request": "..."})
2. AgentTool.run_async():
   a. Creates NEW Runner + InMemorySessionService
   b. Copies parent state (excluding _adk* keys) into child session
   c. Runs ResearchAgent:
      - ResearchAgent yields events internally
      - State deltas forwarded: tool_context.state.update(event.actions.state_delta)
      - Final content captured
   d. Returns merged final text (thought parts filtered)
3. Tool result packaged as FunctionResponse
4. Orchestrator LLM sees: "Research findings: ..." as tool result
5. Orchestrator continues normally

CRITICAL: ResearchAgent's individual events are NOT visible to Orchestrator.
Only the final text result returns. State deltas ARE forwarded.
```

### 7.6 LoopAgent with Escalation

```
review_loop = LoopAgent(
    max_iterations=3,
    sub_agents=[
        LlmAgent(name="Writer", output_key="draft", ...),
        LlmAgent(name="Critic", tools=[approve_tool], ...),
    ]
)

# approve_tool:
def approve(tool_context: ToolContext):
    tool_context.actions.escalate = True
    return "Approved"

Iteration 1:
  Writer generates draft --> state["draft"] = "..."
  Critic reviews: "Needs improvement" (no escalate)
  ctx.reset_sub_agent_states() -- clear for next iteration

Iteration 2:
  Writer generates improved draft --> state["draft"] = "..."
  Critic calls approve_tool --> event.actions.escalate = True
  LoopAgent detects escalate --> should_exit = True --> break

All events from both iterations yielded upstream.
```

### 7.7 Long-Running Tool (Pause/Resume)

```
1. LLM calls: FunctionCall(name="human_approval", args={"request": "..."})
2. Tool returns: {"status": "pending", "approval_id": "abc123"}
3. Event has long_running_tool_ids={"fc_001"}
4. is_final_response() --> True (long_running_tool_ids is truthy)
5. should_pause_invocation() --> True
6. Invocation pauses, client notified

--- time passes, human approves ---

7. Client sends FunctionResponse(id="fc_001", response={"approved": True})
8. Runner resumes invocation from checkpoint
9. LLM sees tool result in history, continues normally
```

### 7.8 Transfer Between Agents

```
root = LlmAgent(
    name="Router",
    sub_agents=[
        LlmAgent(name="BillingAgent", ...),
        LlmAgent(name="TechSupport", ...),
    ]
)

User: "I have a billing question"

1. Router LLM calls: transfer_to_agent(agent_name="BillingAgent")
2. Event.actions.transfer_to_agent = "BillingAgent"
3. Flow recursively runs BillingAgent.run_async(ctx) -- same context
4. BillingAgent responds to user
5. All BillingAgent events yielded upstream through Router

On next user message:
6. Runner._find_agent_to_run() checks last event's transfer_to_agent
7. Routes directly to BillingAgent (bypasses Router)
```

---

## 8. Mapping to Asya: Patterns We Must Support

### 8.1 Pattern Mapping Matrix

| # | ADK Pattern | Asya Equivalent | Status | Gap |
|---|---|---|---|---|
| 1 | ReAct while-loop | Flow DSL while-loop + conditional | Partial | Free variable serialization (1irj) |
| 2 | Streaming tokens (partial) | Upstream events (sidecar --> gateway) | Done | -- |
| 3 | Parallel tool execution | Fan-out (list yield or gather) | Partial | Flow-level parallel await |
| 4 | `transfer_to_agent` | Conditional router (dynamic `route.next`) | Partial | Static conditions only |
| 5 | `output_key` enrichment | Payload mutations (`state["key"] = result`) | Done | -- |
| 6 | SequentialAgent | Route chain (actor1 --> actor2 --> ...) | Done | -- |
| 7 | ParallelAgent | Fan-out with branch tracking | Partial | Branch-isolated history |
| 8 | LoopAgent | While-loop with escalate condition | Partial | Missing `escalate` as first-class action |
| 9 | AgentTool (agent-as-tool) | Actor call (await sub_agent) | Done | Events absorbed naturally |
| 10 | Long-running tools (pause/resume) | Task pause/resume (epic 1ixy) | Done | -- |
| 11 | Tool confirmation | Human-in-the-loop (1c0d/1f7am4) | Slopped | `input_required` state |
| 12 | Before/after model callbacks | No direct equivalent | Missing | Pre/post processing actors |
| 13 | Before/after tool callbacks | No direct equivalent | Missing | Could be sidecar middleware |
| 14 | State deltas (event-carried) | Payload mutations | Done | Different mechanism (payload vs delta) |
| 15 | Event compaction | No equivalent | Missing | Context window management |
| 16 | Tool authentication | Secrets management (1igs) | Slopped | Research phase |
| 17 | Agent branch isolation | No equivalent | Missing | Per-branch message filtering |
| 18 | Streaming tools (live mode) | Not applicable | N/A | Asya is queue-based, not bidi |

### 8.2 Critical Gaps (Must Address for Full Agentic Support)

**Gap 1: Free Variable Serialization (epic 1irj)**

The ReAct loop pattern requires local variables to survive across actor boundaries.
Without auto-serialization, the user must manually pack/unpack from payload:

```python
# ADK (in-process, variables survive naturally)
async def react(state):
    while True:
        state = await llm_call(state)
        tool_calls = state.get("tool_calls", [])  # 'tool_calls' is fine (in payload)
        if tool_calls:
            state = await tool_executor(state)
        else:
            break
```

In Asya, this compiles to routers. The `tool_calls` reference is safe because it reads
from `state` (the payload). But any local variable would be lost.

**Gap 2: Dynamic Routing (transfer_to_agent)**

ADK's `transfer_to_agent` is LLM-decided at runtime. Asya's conditional routers
use static conditions compiled from flow source. Supporting dynamic routing requires
either:
- A "dispatcher" actor that reads a routing field from the payload
- VFS-based route modification (`/proc/asya/msg/route/next`)
- A runtime-evaluated condition in the router

**Gap 3: Parallel Actor Calls in Flow DSL**

ADK's `asyncio.gather(*tasks)` for parallel tool execution maps to fan-out in Asya.
The flow DSL supports fan-out via list yield but not parallel `await` with join:

```python
# ADK: parallel tool execution (automatic when LLM requests multiple tools)
results = await asyncio.gather(tool_a(args), tool_b(args))

# Asya flow: would need something like
state = await [tool_a, tool_b](state)  # not supported
```

**Gap 4: Escalation as First-Class Action**

ADK's `escalate` is set via `tool_context.actions.escalate = True` and breaks
the LoopAgent. Asya's while-loop uses `break` in flow DSL, which requires the
condition to be computable from the payload. An actor would need to set a
payload field (e.g. `state["_escalate"] = True`) and the loop condition router
would check it.

### 8.3 What Already Maps Cleanly

1. **Sequential pipeline** = actor route chain. Direct analog.
2. **Streaming** = upstream events via sidecar HTTP. Already working.
3. **Tool execution** = actor call. Each tool is a separate actor.
4. **State passing** = message payload. The payload IS the state.
5. **Pause/resume** = task pause/resume. Already implemented.
6. **Agent-as-tool** = standard actor call. Sub-agent returns result via queue.

### 8.4 Architectural Insight: Deltas vs Full State

ADK's key design principle is that **everything is an event, and events flow upward**.
The event stream is the universal communication channel.

In Asya, the analogous principle is that **everything is a message, and messages
flow along routes**. The message payload is the universal state container.

The fundamental difference:
- ADK: events carry **deltas** (state changes) alongside content
- Asya: messages carry the **full state** (enriched payload)

ADK's delta-based approach requires a central session store to apply deltas.
Asya's full-state approach is naturally distributed (each actor gets the complete
payload). Both are valid; Asya's approach is simpler for distributed execution
but requires payload discipline (don't store unnecessary data).

---

## References

- [ADK Event Loop docs](https://google.github.io/adk-docs/runtime/event-loop/)
- [ADK Events docs](https://google.github.io/adk-docs/events/)
- [ADK Tools docs](https://google.github.io/adk-docs/tools/)
- [ADK Custom Tools Performance](https://google.github.io/adk-docs/tools-custom/performance/)
- [ADK Callbacks docs](https://google.github.io/adk-docs/callbacks/)
- [ADK LLM Agents docs](https://google.github.io/adk-docs/agents/llm-agents/)
- [ADK Workflow Agents docs](https://google.github.io/adk-docs/agents/workflow-agents/)
- [ADK Python source](https://github.com/google/adk-python)
