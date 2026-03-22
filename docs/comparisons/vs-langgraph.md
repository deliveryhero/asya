# vs LangGraph

## TL;DR

LangGraph is an in-process state-machine framework for building agent graphs in
Python. Asya is a distributed actor mesh on Kubernetes where each agent runs as
an independent pod communicating through message queues. LangGraph gives you the
fastest path from notebook to working agent; Asya gives you per-agent scaling,
fault isolation, and zero SDK lock-in when you move to production.

## At a Glance

| | 🎭 | LangGraph |
|---|---|---|
| **One-liner** | Actor mesh on Kubernetes | In-process agent state machine |
| **Execution model** | Choreography: each message carries its route | Orchestration: StateGraph executes nodes sequentially |
| **Handler contract** | Plain `dict -> dict` function | Node function receiving/returning `TypedDict` state |
| **Scaling** | Per-actor via KEDA (0-N pods each) | Single process; LangGraph Platform for managed scaling |
| **Scale to zero** | 🟢 Native (KEDA) | 🔴 (Platform keeps instances warm) |
| **Failure isolation** | ✅ Per actor (queue buffers on crash) | 🔴 Whole graph fails together |
| **State management** | Payload in envelope + state proxy (S3/Redis) | TypedDict with reducer annotations + checkpointer backends |
| **Checkpointing** | S3 checkpoint via `x-pause` / `x-resume` | Built-in checkpointers (SQLite, Postgres, memory) |
| **Streaming** | FLY events via SSE across distributed actors | 5 modes: values, updates, messages, events, custom |
| **Human-in-the-loop** | ✅ Pause/resume via S3 checkpoint | ✅ `interrupt()` with automatic checkpointing |
| **Dynamic routing** | ✅ Actors rewrite `route.next` at runtime | ✅ Conditional edges between nodes |
| **SDK requirement** | ✅ None | 🔴 LangGraph + LangChain ecosystem |
| **Protocol support** | ✅ A2A + MCP gateway | 🔴 (custom API or LangGraph Platform endpoints) |
| **K8s native** | 🟢 CRD + Crossplane + Helm | 🔴 Can deploy on K8s, no CRD integration |
| **Best for** | Production multi-agent systems at scale | Rapid prototyping and single-process agent graphs |
| **Maturity** | 🟡 Alpha (production at Delivery Hero) | 🟢 Production (widely adopted, LangChain ecosystem) |

## Architecture

### LangGraph: StateGraph with Nodes and Edges

LangGraph models agents as a directed graph. You define **nodes** (Python
functions), connect them with **edges** (static or conditional), and pass a
shared **state** object (a `TypedDict`) through the graph. The `StateGraph`
runtime executes nodes, applies reducer functions to merge state updates, and
optionally checkpoints state to a database for resumption.

```
StateGraph -> Node A -> conditional_edge -> Node B or Node C -> END
                                    ^                  |
                                    |   (cycle back)   |
                                    +------------------+
```

Everything runs in a single Python process. LangGraph Platform adds a managed
server layer with persistence, cron jobs, and an HTTP API -- but the execution
model remains single-process per graph invocation.

### Asya: Actor Mesh with Envelope Routing

Asya decomposes the graph into independent **actors**, each running as a
Kubernetes pod with a sidecar. Messages (**envelopes**) carry their own route
through the mesh. There is no central graph executor -- each actor reads from its
queue, runs the handler, and the sidecar forwards the envelope to the next queue.

```
Queue A -> [Sidecar -> Handler -> Sidecar] -> Queue B -> [Sidecar -> Handler -> Sidecar] -> ...
```

Actors can dynamically rewrite the route at runtime (`yield "SET",
".route.next[:0]", ["human-review"]`), enabling the same conditional branching
as LangGraph's conditional edges -- but decided per-message, not per-graph.

## Developer Experience

The same ReAct tool-calling agent in both frameworks:

### LangGraph

```python
from langgraph.graph import StateGraph, MessagesState, END
from langgraph.prebuilt import ToolNode

def agent(state: MessagesState):
    response = model.invoke(state["messages"])
    return {"messages": [response]}

def should_continue(state: MessagesState):
    last = state["messages"][-1]
    if last.tool_calls:
        return "tools"
    return END

tools = ToolNode([web_search, calculator])

graph = StateGraph(MessagesState)
graph.add_node("agent", agent)
graph.add_node("tools", tools)
graph.set_entry_point("agent")
graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
graph.add_edge("tools", "agent")

app = graph.compile(checkpointer=MemorySaver())
result = app.invoke({"messages": [("user", "What is 2+2?")]})
```

You define nodes, wire edges, compile, and invoke. The `StateGraph` manages
execution order, state merging, and checkpointing. Adding a new tool means
adding it to the `ToolNode` list.

### Asya

```python
from asya_lab.flow import flow

@flow
async def react_agent(state: dict) -> dict:
    while True:
        state = await llm_reason(state)

        if not state.get("tool_calls"):
            break

        tool = state["tool_calls"][0]["name"]
        if tool == "web_search":
            state = await web_search(state)
        elif tool == "calculator":
            state = await calculator(state)

        if state["iteration"] >= 10:
            break

    return state
```

Each `await` call is a separate actor. The flow compiler transforms this Python
into a distributed actor graph using CPS (continuation-passing style). The
`while` loop becomes a message cycle between actors. No graph DSL, no edge
definitions -- standard Python control flow.

Each actor handler is a plain function with no imports:

```python
def web_search(state: dict) -> dict:
    state["observation"] = search_api(state["tool_calls"][0]["args"]["query"])
    return state
```

## When to Choose LangGraph

- **Rapid prototyping** -- StateGraph gets you from idea to working agent in
  minutes. No infrastructure to set up.
- **Rich streaming** -- five streaming modes (values, updates, messages, events,
  custom) give fine-grained control over what clients see during execution.
- **Sophisticated checkpointing** -- built-in checkpointers (SQLite, Postgres)
  with automatic state snapshots at every node. Time-travel debugging lets you
  replay from any checkpoint.
- **LangChain ecosystem** -- native integration with LangChain's model
  abstractions, tool definitions, retrievers, and output parsers.
- **LangGraph Platform** -- managed deployment with built-in persistence, cron
  jobs, and an HTTP/WebSocket API. Removes the need to build your own serving
  layer.
- **Sub-second latency** -- in-process execution means zero network overhead
  between nodes. Critical for interactive chat agents.

## When to Choose Asya

- **Independent scaling** -- GPU inference actors scale 0-10 while routing actors
  scale 0-100, each based on its own queue depth. LangGraph runs all nodes in
  one process.
- **Scale to zero** -- KEDA scales idle actors to zero pods. GPU agents cost
  nothing between requests. LangGraph workers must stay warm.
- **Fault isolation** -- one actor crashing does not affect other actors. In
  LangGraph, a failing node crashes the entire graph invocation.
- **No SDK lock-in** -- handlers are plain `dict -> dict` functions. No
  LangChain imports, no TypedDict schemas, no reducer annotations. Swap a
  handler, redeploy.
- **Multi-team ownership** -- each actor is an independent Kubernetes deployment
  with its own image, scaling policy, and release cycle. Different teams can own
  different pipeline stages.
- **Infrastructure as configuration** -- retry policies, timeouts, scaling
  thresholds, and error routing are declared in YAML manifests, not embedded in
  Python code.
- **Protocol interoperability** -- built-in A2A and MCP gateway lets external AI
  agents and LLM clients interact with the mesh through standard protocols.
- **Dynamic routing at runtime** -- actors rewrite `route.next` per message,
  enabling patterns like LLM judges that route different inputs through different
  paths without recompiling the graph.

## Complementary Use

The two approaches are not mutually exclusive. A LangGraph agent can run inside
an Asya actor -- the framework handles in-process tool orchestration while Asya
handles distributed execution, scaling, and fault tolerance:

```python
# handler.py -- LangGraph agent running inside an Asya actor
def handler(payload: dict) -> dict:
    result = langgraph_app.invoke({"messages": payload["messages"]})
    return {**payload, "response": result["messages"][-1].content}
```

Use LangGraph for complex in-process agent logic. Use Asya to distribute,
scale, and operate those agents in production.
