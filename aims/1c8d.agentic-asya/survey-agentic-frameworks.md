# Agentic Framework Survey

> **Purpose**: Survey how major AI agent/tool frameworks define handlers, tools, agents, and data flow.
> Inform Asya's handler syntax design decisions and confirm that Asya's yield-based ABI is more generic than existing framework signatures — enabling mechanical migration from any of them.
>
> **Date**: 2026-02-09
> **Updated**: 2026-02-15

## Executive Summary

This document compares 14 AI agent frameworks across five dimensions:
1. **Tool/handler definition syntax** — how developers write the functions
2. **Agent definition** — how agents are configured
3. **Data flow** — how state passes between steps/agents
4. **Streaming** — how frameworks handle real-time event emission
5. **Type system** — how inputs/outputs are typed

### Key Finding: Universal Patterns

Despite significant differences, **all frameworks converge on the same core pattern**:

```
Plain Python function + type annotations + docstring = tool
```

The variations are in:
- Whether a **decorator** is required (`@tool`, `@function_tool`, `@beta_tool`) vs. plain functions
- Whether inputs use **Pydantic models** vs. plain type hints
- Whether outputs are **strings**, **dicts**, or **typed models**
- How **state/context** is injected (magic parameter name, decorator, or explicit)
- How **streaming** is exposed (async generators, stream objects, state deltas, or event buses)

---

## Comparison Matrix: Tool Definition Syntax

| Framework | Decorator Required? | Input Typing | Output Typing | State Access | Example |
|-----------|-------------------|-------------|--------------|-------------|---------|
| **Google ADK** | No | Type hints | `-> dict` | Session state via `output_key` | `def get_weather(city: str) -> dict:` |
| **smolagents** | `@tool` or `Tool` subclass | Type hints + docstring `Args:` | `-> str` (or typed) | `agent.state` dict | `@tool def search(query: str) -> str:` |
| **CrewAI** | `@tool` or `BaseTool` subclass | Pydantic `BaseModel` + `Field` | `-> str` (always) | Task `context` list | `@tool("name") def f(q: str) -> str:` |
| **LlamaIndex** | No (auto-wrapped) | Type hints + `Annotated` | `-> str` or `ToolOutput` | `ctx: Context` param | `def multiply(a: float, b: float) -> float:` |
| **OpenAI Swarm** | No | Type hints + docstring | `-> str`, `Result`, or `Agent` | `context_variables` param | `def f(context_variables, city: str):` |
| **OpenAI Agents SDK** | `@function_tool` | Type hints, Pydantic, TypedDict | `-> str` or content types | `RunContextWrapper[T]` param | `@function_tool async def f(city: str) -> str:` |
| **AutoGen** | No (wrapped in `FunctionTool`) | Type hints + `Annotated` | Any (stringified) | `CancellationToken` param | `async def search(query: str) -> str:` |
| **Agno** | `@tool` or `Toolkit` class | Type hints + Pydantic | `-> str` or `ToolResult` | `run_context: RunContext` param | `@tool def f(city: str) -> str:` |
| **Mastra** (TS) | `createTool()` factory | Zod schema (`z.object()`) | Zod schema | `ToolExecutionContext` param | `createTool({ inputSchema: z.object({...}), execute: ... })` |
| **Anthropic SDK** | `@beta_tool` or raw JSON Schema | Type hints or JSON Schema | `-> str` (serialized) | Not built-in | `@beta_tool def f(city: str) -> str:` |
| **BeeAI** | `@tool` or `Tool` subclass | Pydantic `BaseModel` + `Field` | `StringToolOutput` | `RunContext` param | `@tool def f(expr: str) -> StringToolOutput:` |
| **DSPy** | No (wrapped in `dspy.Tool`) | Type hints + docstring | Return value (any) | N/A (stateless) | `def search(query: str) -> str:` |
| **LangGraph** | `@tool` decorator | Type hints + docstring | Any (serializable) | `InjectedState` annotation | `@tool def f(query: str) -> str:` |

---

## Comparison Matrix: Data Flow Patterns

| Framework | Data Flow Model | State Container | Enrichment Pattern? |
|-----------|----------------|----------------|-------------------|
| **Google ADK** | Session state dict + `output_key` per agent | `ctx.session.state` (shared dict) | Yes — `output_key` writes to shared state |
| **smolagents** | Agent state dict + memory steps | `agent.state` dict | No — tools return strings, LLM decides |
| **CrewAI** | Task context (output of previous task) | Flow state (`Flow[StateModel]`) | Partial — task outputs chain |
| **LlamaIndex** | Shared `Context.store` + typed events | `ctx.store.get/set` (key-value) | Yes — tools write to store |
| **OpenAI Swarm** | `context_variables` dict (passed manually) | Mutable dict | Yes — functions update context_variables |
| **OpenAI Agents SDK** | `RunContextWrapper[T]` (typed, shared) | Typed context object | No — context is local, not serialized |
| **AutoGen** | Shared message context (all agents see all messages) | Chat history + memory objects | No — message-based |
| **Agno** | `session_state` dict + `RunContext` | Persisted dict | Yes — tools modify session_state |
| **Mastra** (TS) | Step output -> next step input (typed) | Workflow `state` + `setState()` | Yes — state accumulates via `setState` |
| **Anthropic SDK** | Messages array (manual threading) | None built-in | No — message-based |
| **BeeAI** | Agent memory + workflow shared state | Memory + `AgentWorkflow` state | Partial — sequential agent outputs |
| **DSPy** | Explicit `Prediction` objects between modules | None — explicit passing | No — explicit data threading |
| **LangGraph** | Shared mutable state with typed reducers | `TypedDict` with `Annotated` reducers | Yes — state accumulates via reducers |

---

## Comparison Matrix: Core Capabilities

| Framework | Streaming | Short Memory | Long Memory | Persistence | Multi-Agent | Workflows |
|-----------|-----------|-------------|-------------|-------------|-------------|-----------|
| **Google ADK** | Yes (SSE events) | Yes (session) | Yes (session state) | Yes (session service) | Yes (sub-agents, SequentialAgent, LoopAgent) | Yes (custom agents) |
| **smolagents** | Yes (generator) | Yes (AgentMemory) | No | Partial (save/load) | Yes (managed_agents) | No |
| **CrewAI** | Yes (event bus) | Yes (ChromaDB) | Yes (SQLite) | Yes (`@persist`) | Yes (sequential, hierarchical) | Yes (Flows with `@start/@listen/@router`) |
| **LlamaIndex** | Yes (typed events) | Yes (Memory blocks) | Yes (vector blocks) | Yes (`ctx.to_dict()`) | Yes (handoffs) | Yes (event-driven Workflow) |
| **OpenAI Swarm** | Basic | No (manual) | No | No (stateless) | Yes (return Agent) | No |
| **OpenAI Agents SDK** | Yes (typed events) | Yes (Sessions) | Yes (SQLAlchemy, Dapr) | Yes (multiple backends) | Yes (handoffs) | No |
| **AutoGen** | Yes (`run_stream()`) | Yes (ListMemory) | Yes (ChromaDB, Redis) | Yes (`save_state/load_state`) | Yes (RoundRobin, Selector, Swarm, MagenticOne) | No |
| **Agno** | Yes (RunEvent types) | Yes (chat history) | Yes (learned facts in DB) | Yes (13+ DB backends) | Yes (Teams: supervisor, router, broadcast) | Yes (Step, Parallel, Condition, Loop) |
| **Mastra** (TS) | Yes (textStream) | Yes (message history) | Yes (semantic recall) | Yes (LibSQL, PostgreSQL) | Yes (sub-agents as tools) | Yes (.then, .branch, .parallel, loops) |
| **Anthropic SDK** | Yes (SSE) | No (manual) | No | No | No | No |
| **BeeAI** | Yes (event emitter) | Yes (UnconstrainedMemory) | Yes (persistent) | Yes (save/load) | Yes (AgentWorkflow, HandoffTool) | Yes (AgentWorkflow) |
| **DSPy** | Limited | No | No | Yes (optimized programs) | No | No (compose via modules) |
| **LangGraph** | Yes (5 modes) | Yes (checkpointers) | Yes (stores) | Yes (Postgres, MongoDB) | Yes (supervisor, subgraphs) | Yes (graph-based) |

---

## Detailed Framework Summaries

### 1. Google ADK (Agent Development Kit)

**Language**: Python, TypeScript, Go, Java
**Key insight**: Tools are plain functions. Agents share state via `output_key` enrichment into session state.

```python
from google.adk.agents import Agent

def get_weather(city: str) -> dict:
    """Retrieves current weather for a specified city."""
    return {"status": "success", "report": "Sunny, 25C"}

root_agent = Agent(
    name="weather_agent",
    model="gemini-2.0-flash",
    description="Answers weather questions",
    instruction="You are a helpful weather agent.",
    tools=[get_weather],
)
```

**State flow**: ADK uses `output_key` on LLM sub-agents to write results into shared session state. Tools access state via session context. The enrichment pattern is first-class — each agent's `output_key` names the state field where its output is stored.

```python
story_generator = LlmAgent(
    name="StoryGenerator",
    model=GEMINI_2_FLASH,
    instruction="Write a story about {topic}",
    output_key="current_story",  # Result stored as state["current_story"]
)
```

**Streaming**: ADK agents use async generators. Custom agents override `_run_async_impl` to yield events:

```python
async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
    async for event in self.llm.generate_content_async(request, stream=True):
        yield event  # Partial text, tool calls, etc.
```

---

### 2. HuggingFace smolagents

**Language**: Python
**Key insight**: Code-first agents that generate Python code for tool calls (not JSON).

```python
from smolagents import tool, CodeAgent

@tool
def model_download_tool(task: str) -> str:
    """Returns the most downloaded model for a given task.

    Args:
        task: The task category (e.g., text-classification).
    """
    from huggingface_hub import list_models
    model = next(iter(list_models(filter=task, sort="downloads", direction=-1)))
    return model.id

agent = CodeAgent(tools=[model_download_tool], model=model)
result = agent.run("What's the most popular text-to-video model?")
```

**Type contract**: Docstring `Args:` section is mandatory for parameter descriptions. Type hints define the schema. Return type is typically `str`.

**Multi-agent**: Hierarchical via `managed_agents` — sub-agents appear as functions in the manager's code generation.

---

### 3. CrewAI

**Language**: Python
**Key insight**: Role/goal/backstory triple for agents. Flows use decorator-based DAG (`@start/@listen/@router`).

```python
from crewai.tools import tool, BaseTool
from pydantic import BaseModel, Field

# Decorator approach
@tool("Search")
def search(query: str) -> str:
    """Search the web for information."""
    return "search results..."

# Class approach with Pydantic schema
class SearchInput(BaseModel):
    query: str = Field(..., description="The search query")

class SearchTool(BaseTool):
    name: str = "search"
    description: str = "Search the web"
    args_schema: Type[BaseModel] = SearchInput

    def _run(self, query: str) -> str:
        return "results..."
```

**Flows** (event-driven DAG):
```python
from crewai.flow.flow import Flow, listen, start, router
from pydantic import BaseModel

class OrderState(BaseModel):
    order_data: dict = {}
    validated: bool = False

class OrderFlow(Flow[OrderState]):
    @start()
    def receive_order(self):
        self.state.order_data = {"item": "widget", "qty": 5}

    @listen(receive_order)
    def validate_order(self):
        self.state.validated = True

    @router(validate_order)
    def route_order(self):
        return "process" if self.state.validated else "reject"
```

**Data flow**: Task `context` parameter creates explicit dependencies between tasks. Sequential tasks auto-chain output to input.

**Streaming**: Event bus with `BaseEventListener`:

```python
class MyListener(BaseEventListener):
    def setup_listeners(self, crewai_event_bus):
        @crewai_event_bus.on(LLMStreamChunkEvent)
        def on_chunk(source, event):
            print(event.chunk, end="")
```

---

### 4. LlamaIndex

**Language**: Python
**Key insight**: Tools are plain functions auto-wrapped to `FunctionTool`. Workflows use typed Pydantic events for inter-step communication.

```python
# Simplest form -- plain function, auto-detected
def multiply(a: float, b: float) -> float:
    """Multiply two numbers and returns the product"""
    return a * b

agent = FunctionAgent(tools=[multiply, add], llm=llm)
```

**State-aware tools** via `Context` parameter (auto-injected, hidden from LLM):
```python
from llama_index.core.workflow import Context

async def set_name(ctx: Context, name: str) -> str:
    """Set the user's name."""
    async with ctx.store.edit_state() as state:
        state["state"]["name"] = name
    return f"Name set to {name}"
```

**Workflows** (event-driven steps):
```python
class JokeEvent(Event):
    joke: str

class JokeFlow(Workflow):
    @step
    async def generate_joke(self, ev: StartEvent) -> JokeEvent:
        response = await self.llm.acomplete(f"Write a joke about {ev.topic}")
        return JokeEvent(joke=str(response))

    @step
    async def critique_joke(self, ev: JokeEvent) -> StopEvent:
        response = await self.llm.acomplete(f"Rate this joke: {ev.joke}")
        return StopEvent(result=str(response))
```

**Streaming**: Workflow steps emit events to a side-channel:

```python
@step
async def generate_joke(self, ev: StartEvent) -> JokeEvent:
    async for chunk in self.llm.astream_complete(prompt):
        ctx.write_event_to_stream(ProgressEvent(msg=chunk.delta))
    return JokeEvent(joke=full_text)
```

---

### 5. OpenAI Swarm (Deprecated) + Agents SDK

**Language**: Python
**Key insight**: Swarm pioneered minimal, zero-abstraction agents. Agents SDK is the production successor with sessions, guardrails, and tracing.

**Swarm** (plain functions, zero decorators):
```python
from swarm import Agent

def get_weather(location: str) -> str:
    """Get the weather for a location."""
    return "Sunny, 25C"

def transfer_to_sales(context_variables):
    """Transfer to sales department."""
    return sales_agent  # Returning an Agent triggers handoff

agent = Agent(
    name="Triage",
    instructions="Route customer requests.",
    functions=[get_weather, transfer_to_sales],
)
```

**Agents SDK** (typed context, sessions, guardrails):
```python
from agents import Agent, function_tool, RunContextWrapper
from dataclasses import dataclass

@dataclass
class AppContext:
    user_id: str
    db_conn: object

@function_tool
async def fetch_weather(city: str) -> str:
    """Fetch the weather for a given city."""
    return f"Sunny in {city}"

@function_tool
async def lookup_user(ctx: RunContextWrapper[AppContext]) -> str:
    """Look up user info."""
    return f"User {ctx.context.user_id}"

agent = Agent[AppContext](
    name="Assistant",
    tools=[fetch_weather, lookup_user],
    handoffs=[billing_agent],
    output_type=CalendarEvent,  # Pydantic structured output
)
```

**State flow**: Swarm uses `context_variables` dict (passed back manually between turns). Agents SDK uses typed `RunContextWrapper[T]` shared across all tools in a run, plus Sessions for cross-turn persistence.

**Streaming**: Runner returns a stream object:

```python
result = Runner.run_streamed(agent, "Hello!")
async for event in result.stream_events():
    if event.type == "raw_response_event":
        ...  # Token-level streaming
```

---

### 6. Microsoft AutoGen

**Language**: Python
**Key insight**: Two-layer architecture. Core uses pub/sub messaging with `RoutedAgent`. AgentChat provides high-level team presets.

```python
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient

# Tools are plain functions
async def web_search(query: str) -> str:
    """Find information on the web"""
    return "AutoGen is a multi-agent framework."

def calculator(a: int, b: int, operator: Annotated[Operator, "operator"]) -> int:
    if operator == "+": return a + b
    elif operator == "-": return a - b

agent = AssistantAgent(
    name="assistant",
    model_client=OpenAIChatCompletionClient(model="gpt-4o"),
    tools=[web_search, calculator],
    handoffs=["specialist"],
    memory=[user_memory],
)
```

**Multi-agent teams**:
```python
from autogen_agentchat.teams import RoundRobinGroupChat, SelectorGroupChat, Swarm

team = RoundRobinGroupChat([primary, critic], termination_condition=termination)
result = await team.run(task="Write a poem about autumn.")
```

**Core level** (pub/sub, for distributed systems):
```python
class MyAgent(RoutedAgent):
    @message_handler
    async def handle(self, message: MyMessageType, ctx: MessageContext) -> ResponseMessage:
        return ResponseMessage(reply=f"Processed: {message.content}")
```

---

### 7. Agno (formerly PHI/phidata)

**Language**: Python
**Key insight**: 100+ built-in tool integrations. Session state dict with persistence to 13+ DB backends. Agent-level learning (auto-extract user facts).

```python
from agno.agent import Agent
from agno.tools import tool
from agno.run import RunContext

@tool
def get_weather(city: str) -> str:
    """Get the weather for the given city.

    Args:
        city (str): The city to get the weather for.
    """
    return f"Sunny in {city}"

# State-aware tool
def add_item(run_context: RunContext, item: str) -> str:
    """Add an item to the shopping list."""
    run_context.session_state["shopping_list"].append(item)
    return f"Added: {item}"

agent = Agent(
    model=Claude(id="claude-sonnet-4-5"),
    tools=[get_weather, add_item],
    session_state={"shopping_list": []},
    enable_agentic_state=True,
    update_memory_on_run=True,  # Auto-learn user facts
    db=SqliteDb(db_file="agent.db"),
)
```

**Workflows**:
```python
from agno.workflow import Workflow

workflow = Workflow(
    name="Content Creation",
    steps=[researcher, writer],  # Sequential agents
    session_state={"topic": ""},
)
```

Step types: `Step`, `Parallel`, `Condition`, `Loop`, `Router`. Each step receives `previous_step_outputs` dict.

**Streaming**: RunEvent-typed events:

```python
async for event in agent.arun("query", stream=True, stream_events=True):
    if event.event == RunEvent.run_content:
        print(event.content, end="")
```

---

### 8. Mastra (TypeScript)

**Language**: TypeScript
**Key insight**: Zod schemas everywhere. Typed steps with `.then()/.branch()/.parallel()` chaining. Suspend/resume for human-in-the-loop.

```typescript
import { createTool } from "@mastra/core/tools";
import { z } from "zod";

const weatherTool = createTool({
  id: "get-weather",
  description: "Get current weather for a location",
  inputSchema: z.object({
    location: z.string().describe("City name"),
  }),
  outputSchema: z.object({
    temperature: z.number(),
    conditions: z.string(),
  }),
  execute: async (inputData) => ({
    temperature: 22,
    conditions: "Sunny",
  }),
});

const weatherAgent = new Agent({
  name: "Weather Agent",
  instructions: "You are a helpful weather assistant.",
  model: "openai/gpt-5.1",
  tools: { weatherTool },
});
```

**Workflows with typed step chaining**:
```typescript
const workflow = createWorkflow({
  id: "user-onboarding",
  inputSchema: z.object({ email: z.string() }),
  outputSchema: z.object({ name: z.string(), email: z.string() }),
})
  .then(validateStep)
  .then(enrichStep)
  .commit();
```

**Streaming**:
```typescript
const stream = await agent.stream("What's the weather?");
for await (const chunk of stream.textStream) {
    process.stdout.write(chunk);
}
```

---

### 9. Anthropic Claude SDK

**Language**: Python, TypeScript, Java, Ruby
**Key insight**: Thin client, no agent abstraction. Three tool definition approaches: raw JSON Schema, `@beta_tool` decorator, Zod helpers.

```python
from anthropic import beta_tool

@beta_tool
def get_weather(location: str, unit: str = "fahrenheit") -> str:
    """Get the current weather in a given location.

    Args:
        location: The city and state, e.g. San Francisco, CA
        unit: Temperature unit, either 'celsius' or 'fahrenheit'
    """
    return json.dumps({"temperature": "20C", "condition": "Sunny"})

# Tool runner automates the agentic loop
runner = client.beta.messages.tool_runner(
    model="claude-opus-4-6",
    tools=[get_weather],
    messages=[{"role": "user", "content": "Weather in SF?"}],
)
final = runner.until_done()
```

**Data flow**: Conversation messages array is the only state. Tools return strings. No shared state between tools — only the LLM sees all tool results.

---

### 10. BeeAI Agent Framework

**Language**: Python, TypeScript
**Key insight**: Controlled tool invocation via `RequirementAgent`. Pydantic models for input schemas. Event emitter for observability.

```python
from beeai_framework.tools import StringToolOutput, tool
from beeai_framework.agents.requirement import RequirementAgent

@tool
def basic_calculator(expression: str) -> StringToolOutput:
    """A calculator that evaluates mathematical expressions.

    Args:
        expression: The expression to evaluate (e.g., "2 + 3 * 4").
    """
    result = eval(expression)
    return StringToolOutput(json.dumps({"result": result}))

agent = RequirementAgent(
    llm=ChatModel.from_name("ollama:granite4:micro"),
    tools=[basic_calculator],
    memory=UnconstrainedMemory(),
)
```

**Multi-agent workflow**:
```python
workflow = AgentWorkflow(name="Smart assistant")
workflow.add_agent(name="Researcher", tools=[WikipediaTool()], llm=llm)
workflow.add_agent(name="Writer", llm=llm)
await workflow.run(inputs=[
    AgentWorkflowInput(prompt="Research the topic.", context=user_input),
    AgentWorkflowInput(prompt="Write a summary."),
])
```

---

### 11. DSPy

**Language**: Python
**Key insight**: Declarative signatures replace prompt engineering. Auto-optimization of prompts/weights via compilers.

```python
import dspy

# Signature defines I/O contract (no prompt engineering)
class QA(dspy.Signature):
    """Answer questions based on context."""
    context: list[str] = dspy.InputField()
    question: str = dspy.InputField()
    answer: str = dspy.OutputField()

# Module composes signatures
class RAG(dspy.Module):
    def __init__(self):
        self.retrieve = dspy.Retrieve(k=3)
        self.generate = dspy.ChainOfThought(QA)

    def forward(self, question):
        context = self.retrieve(question).passages
        return self.generate(context=context, question=question)

# Tools are plain functions wrapped
def search(query: str) -> list[str]:
    """Search Wikipedia."""
    return ["result1", "result2"]

agent = dspy.ReAct("question -> answer", tools=[search])
```

**Data flow**: Explicit `Prediction` objects passed between modules in `forward()`. No shared state. Pure data threading.

**Unique**: Auto-optimization compiles modules into optimized prompts:
```python
optimizer = BootstrapFewShotWithRandomSearch(metric=accuracy, max_bootstrapped_demos=4)
optimized = optimizer.compile(RAG(), trainset=examples)
```

---

### 12. LangGraph

**Language**: Python
**Key insight**: Explicit graph-based control flow. Typed state with reducers. Durable execution with checkpointing.

```python
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langchain.tools import tool

@tool
def search(query: str) -> str:
    """Search the web."""
    return f"Result for {query}"

# Node function: reads state, returns partial update
def call_model(state: MessagesState) -> dict:
    response = llm.invoke(state["messages"])
    return {"messages": [response]}

# Build graph
graph = StateGraph(MessagesState)
graph.add_node("agent", call_model)
graph.add_node("tools", ToolNode([search]))
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", tools_condition)
graph.add_edge("tools", "agent")

agent = graph.compile(checkpointer=InMemorySaver())
```

**State with reducers** (enrichment-like accumulation):
```python
class State(TypedDict):
    query: str
    documents: Annotated[list[str], add]  # Appends on each update
    answer: str                            # Overwrites on each update
```

**Streaming** (5 modes):
```python
for update in agent.stream(inputs, stream_mode="updates"):
    print(update)  # Partial state dict from each node

# Custom streaming from within nodes
from langgraph.types import get_stream_writer
def my_node(state: State):
    writer = get_stream_writer()
    writer({"progress": "50%"})  # Emit custom event mid-execution
    return {"result": "done"}
```

---

## Streaming Patterns

Frameworks use four distinct patterns for real-time event emission:

### Pattern A: Async Generator (ADK, LlamaIndex)

The handler is an async generator that yields events:

```python
# Google ADK — agent._run_async_impl yields Event objects
async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
    async for event in self.llm.generate_content_async(request, stream=True):
        yield event  # Partial text, tool calls, etc.

# LlamaIndex — workflow steps emit typed events to side-channel
class JokeFlow(Workflow):
    @step
    async def generate_joke(self, ev: StartEvent) -> JokeEvent:
        async for chunk in self.llm.astream_complete(prompt):
            ctx.write_event_to_stream(ProgressEvent(msg=chunk.delta))
        return JokeEvent(joke=full_text)
```

### Pattern B: Stream Object (OpenAI Agents SDK, Mastra)

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

### Pattern C: State Updates (LangGraph)

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

### Pattern D: Event Bus (CrewAI, Agno)

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

---

## Cross-Cutting Analysis

### Pattern 1: Tool Definition Convergence

**Every framework** supports plain Python functions with type annotations as the primary tool definition mechanism. The decorator (when required) is purely for registration/metadata — the function body stays the same.

### Pattern 2: State Injection via Magic Parameters

Multiple frameworks inject state/context through specially-named parameters:

| Framework | Magic Parameter | Injected Object |
|-----------|----------------|-----------------|
| Google ADK | `tool_context: ToolContext` | Session state, artifacts, memory |
| OpenAI Swarm | `context_variables` | Shared dict |
| OpenAI Agents SDK | `ctx: RunContextWrapper[T]` | Typed context |
| LlamaIndex | `ctx: Context` | Workflow context + store |
| Agno | `run_context: RunContext` | Session state dict |
| LangGraph | `state: Annotated[dict, InjectedState]` | Graph state |

The parameter is **auto-detected by name or type annotation** and excluded from the tool's public schema.

### Pattern 3: Enrichment/Accumulation is Common

Several frameworks use state enrichment (accumulating results in a shared dict/state):

- **Google ADK**: `output_key` writes agent output to session state
- **LangGraph**: State reducers (e.g., `Annotated[list, add]`) accumulate data
- **Agno**: `session_state` dict enriched by tools via `RunContext`
- **CrewAI Flows**: `self.state` accumulates across `@listen` methods
- **Mastra**: `setState()` merges updates across workflow steps

### Pattern 4: Output Key Naming

Only **Google ADK** has an explicit `output_key` concept that names where an agent's output goes in shared state. All other frameworks either:
- Return strings (tools report to LLM, which synthesizes)
- Return dicts that get merged into state (LangGraph, Agno)
- Return typed events that get routed by type (LlamaIndex Workflows)
- Return Pydantic models validated by schema (OpenAI Agents SDK, CrewAI)

### Pattern 5: Workflow/Pipeline Typing

Frameworks that support typed pipelines (step chaining) use different approaches for ensuring type compatibility:

| Framework | Pipeline Typing Approach |
|-----------|------------------------|
| **Mastra** | Zod schema on each step; step N output schema must match step N+1 input schema |
| **LlamaIndex** | Pydantic Event types; steps connected by event type matching |
| **DSPy** | Signature strings/classes; explicit `Prediction` passing in `forward()` |
| **LangGraph** | TypedDict with reducers; all nodes share the same state type |
| **CrewAI Flows** | `@listen` decorator connects methods; shared `Flow[StateModel]` |

---

## Champion Framework: Google ADK

Based on the 14-framework survey, **Google ADK** is the closest architectural match for a distributed actor-based system:

| ADK Concept | Distributed Actor Equivalent |
|-------------|------------------------------|
| `output_key` (enrichment into shared state) | Payload enrichment pattern |
| Plain functions as tools (no decorator) | "No pip package" principle |
| `SequentialAgent` / `ParallelAgent` / `LoopAgent` | Flow DSL (sequential, fan-out, loops) |
| `tool_context: ToolContext` (magic parameter) | Context injection via yield ABI |
| `session.state` prefix scoping (`user:`, `app:`, `temp:`) | Multi-tenant payload namespacing |
| Event-based async generators | Yield-based frame emission |

**Runner-up: LangGraph** for its state reducer concept (typed merge strategies for enrichment) and 5-mode streaming architecture.

---

## Framework Philosophy Spectrum

```
Minimal/DIY <------------------------------------------------------> Batteries-Included

Anthropic SDK    OpenAI Swarm    DSPy    smolagents    LangGraph    AutoGen    Agno
   |                |             |         |             |           |         |
   |                |             |         |             |           |         |
 Raw API        Plain funcs   Signatures  @tool +     StateGraph   Teams +   100+ tools
 No agent       context_vars  Modules     CodeAgent   Reducers    Memory    Memory+State
 No state       No persist    Optimize    Managed     Checkpoint  Persist   Learning
                              prompts     agents      Streaming   Streaming Streaming
```

All 14 frameworks run **in-process**. None decompose into separate processes/containers communicating via message queues. A distributed actor mesh is architecturally distinct — the handler contract must be simple enough that functions written for any of these frameworks can be deployed as distributed actors with minimal or no modification.
