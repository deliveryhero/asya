# 🎭 Asya vs Google ADK

## TL;DR

Google ADK is an in-process agent framework: agents, tools, and orchestration
all run in a single Python process sharing memory. 🎭 Asya is a distributed actor
mesh where each agent is a separate pod on Kubernetes, communicating through
durable message queues. ADK gives you fast prototyping with Gemini and Vertex AI
integration; 🎭 Asya gives you independent scaling, failure isolation, and
production-grade deployment for multi-agent workloads.

## At a Glance

| | 🎭 Asya | Google ADK |
|---|---|---|
| **One-liner** | Actor mesh on Kubernetes | In-process agent framework |
| **Execution model** | Choreography: route embedded in each message | Orchestration: Runner drives a ReAct loop (`while True` over async generator) |
| **Handler UX** | Pure `dict -> dict` function, zero imports | Plain function + `Agent()` config; `tool_context` param for state access |
| **State passing** | Full state travels in the message payload | Deltas written to shared session; `output_key` saves agent output to state dict |
| **Scaling** | Per-actor via KEDA (queue depth, 0-N) | Single process; scale the whole app |
| **Failure isolation** | 🟢 Per-actor: one crash affects only its queue | 🔴 Per-process: one crash takes down all agents |
| **Multi-agent** | Separate pods, queue-connected | In-process: Sequential, Parallel, Loop, AgentTool, transfer_to_agent |
| **Streaming** | FLY events via sidecar to gateway (SSE) | Async generator yields partial events (not persisted to session) |
| **Human-in-the-loop** | 🟢 Checkpoint to S3, resume from any replica | 🟡 LongRunningFunctionTool pauses in memory; lost on crash |
| **Tool callbacks** | 🔴 Not built-in (use pre/post-processing actors) | 🟢 before/after callbacks on both LLM calls and tool executions |
| **SDK lock-in** | 🟢 None (plain Python) | 🔴 `google-adk` package required |
| **LLM coupling** | 🟢 None; handler calls any LLM | 🟡 Gemini-first; other models via LiteLLM adapter |
| **Protocols** | 🟢 A2A + MCP gateway built-in | 🟡 A2A server built-in; MCP tool consumption only |
| **Deployment** | Kubernetes CRDs, Helm, GitOps | `adk web`, `adk api_server`, or Vertex AI Agent Engine |
| **Transport** | SQS, RabbitMQ, GCP Pub/Sub | In-memory (no transport; direct function calls) |
| **Maturity** | 🟡 Alpha | 🟡 Preview |

## Architecture

**Google ADK** runs everything inside one Python process. The `Runner` drives a
ReAct loop (`while True`) over an async generator (`BaseLlmFlow.run_async`).
Each iteration: preprocess (build LLM request with tools) -> call LLM ->
postprocess (execute tool calls via `asyncio.gather` if any). Tool results feed
back through session history for the next LLM turn. The loop breaks when
`is_final_response()` returns true (text-only response, no pending tool calls).
State lives in a delta-tracked `State` object -- every mutation records a
`state_delta` on the response event, persisted by the Runner.

```
┌─────────────────────────────────────────┐
│ Python Process                          │
│                                         │
│  Runner ─► Agent (async generator)      │
│              │                          │
│              ├─► LLM call (Gemini API)  │
│              ├─► Tool A (in-process)    │
│              ├─► Tool B (in-process)    │
│              └─► Sub-agent (in-process) │
│                                         │
│  Session ◄── delta-tracked state ──►    │
└─────────────────────────────────────────┘
```

**🎭 Asya** decomposes each agent into a separate pod. The sidecar reads from a
queue, invokes the handler over a Unix socket, and routes the result to the next
queue. State travels in the message payload -- no shared memory, no central
session store.

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ Agent A  │────►│ Agent B  │────►│ Agent C  │
│ pod + q  │ msg │ pod + q  │ msg │ pod + q  │
└──────────┘     └──────────┘     └──────────┘
     ▲                                 │
     │          ┌──────────┐           │
     └──────────│ Gateway  │◄──────────┘
                │ A2A/MCP  │
                └──────────┘
```

## Developer Experience: The Same Task in Both

**Task**: research a topic, then write an article based on the research.

### Google ADK

```python
from google.adk.agents import LlmAgent, SequentialAgent

researcher = LlmAgent(
    name="Researcher",
    model="gemini-2.0-flash",
    instruction="Research the topic: {topic}",
    output_key="research",         # result saved to state["research"]
)

writer = LlmAgent(
    name="Writer",
    model="gemini-2.0-flash",
    instruction="Write an article based on: {research}",  # reads from state
)

pipeline = SequentialAgent(
    name="Pipeline",
    sub_agents=[researcher, writer],
)
```

State flows via `output_key`: Researcher writes to `state["research"]`,
Writer reads it via the `{research}` template variable. Both agents share
the same in-memory session. State keys support scope prefixes (`app:`,
`user:`, `temp:`) for cross-session and per-invocation data.

### 🎭 Asya

```python
async def research_pipeline(payload: dict) -> dict:  # asya: flow
    payload = await researcher(payload)  # asya: actor
    payload = await writer(payload)  # asya: actor
    return payload

async def researcher(payload: dict) -> dict:
    """Research the topic."""
    result = call_any_llm(payload["topic"])
    payload["research"] = result
    return payload

async def writer(payload: dict) -> dict:
    """Write an article from research."""
    payload["article"] = call_any_llm(payload["research"])
    return payload
```

`asya flow compile research_pipeline.py` generates one `AsyncActor` manifest per
function. Each deploys as a separate pod with its own queue and scaling policy.
Handlers are plain Python -- no ADK import, no Gemini dependency.

## Key Differences in Practice

### State: Deltas vs Full Payload

ADK tracks changes as deltas on events (`EventActions.state_delta`), applied by
the Runner to a central session service. 🎭 Asya carries the full state in every
message -- no central store, no delta merging, naturally distributed.

### Composition: In-Process vs Distributed

ADK offers five composition modes: `SequentialAgent`, `ParallelAgent`,
`LoopAgent`, `AgentTool` (encapsulated sub-agent as a tool), and
`transfer_to_agent` (LLM-driven dynamic routing). All share one `asyncio` loop.
🎭 Asya's flow compiler transforms the same sequential/parallel/loop patterns into
distributed actors connected by queues, each scaling independently.

### Streaming: Generator vs FLY

ADK yields partial events (`partial=True`) from async generators; these are
forwarded to the UI but not persisted to session history. 🎭 Asya emits FLY events
via the sidecar, streamed over SSE through the gateway -- works across pod
boundaries and survives network partitions.

### Human-in-the-Loop

ADK pauses invocations in memory via `LongRunningFunctionTool` and tool
confirmation (`require_confirmation=True`). State is lost on crash. 🎭 Asya
checkpoints the full envelope to S3 via `x-pause`; any replica can restore
it, surviving pod evictions and node failures.

## When to Choose Google ADK

- **Prototyping with Gemini** -- ADK's Gemini integration is first-class;
  `output_key`, session state, and the ReAct loop work out of the box
- **Single-process agents** -- if all agents fit in one process and you do
  not need independent scaling or failure isolation
- **Vertex AI deployment** -- ADK agents deploy to Vertex AI Agent Engine
  with minimal configuration for managed hosting
- **Rich tool callbacks** -- before/after hooks on both LLM calls and tool
  executions for guardrails, logging, and short-circuiting
- **Dynamic agent routing** -- `transfer_to_agent` lets the LLM decide which
  sub-agent to hand off to at runtime
- **Rapid iteration** -- `adk web` gives you a local UI for testing agents
  interactively

## When to Choose 🎭 Asya

- **Production multi-agent workloads** -- each agent scales independently
  based on its own queue depth (including GPU-bound agents that scale
  differently from CPU agents)
- **Failure isolation** -- one agent crashing, OOMing, or timing out does
  not affect any other agent
- **No SDK lock-in** -- handlers are plain Python functions with zero
  framework imports; portable to any runtime
- **Durable human-in-the-loop** -- envelope checkpointed to S3 survives
  pod evictions, node drains, and cluster migrations
- **Transport flexibility** -- choose SQS, RabbitMQ, or GCP Pub/Sub per
  environment without changing handler code
- **Kubernetes-native GitOps** -- actors are CRDs managed by Crossplane;
  `kubectl apply` and ArgoCD work natively
- **Scale to zero** -- KEDA scales actor pods to zero when queues are empty;
  no idle compute cost
