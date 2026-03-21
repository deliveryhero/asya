# 🎭 Asya as an Agentic Framework

**LangGraph, CrewAI, Google ADK, AutoGen, KAgent**

## TL;DR

Agentic frameworks like LangGraph, CrewAI, Google ADK, and AutoGen provide
abstractions for building AI agents — tool definitions, multi-agent orchestration,
memory, streaming, and human-in-the-loop. They run as in-process Python
applications where agents, tools, and state live in a single runtime. Fast to
prototype, but difficult to scale, isolate, and operate independently.

Asya takes a fundamentally different approach. Each agent runs as an independent
Kubernetes pod communicating through message queues. There is no central
orchestrator — every message carries its own route. Each agent scales
independently (including to zero), crashes without affecting others, and can be
deployed, upgraded, and owned by separate teams. The trade-off is that Asya
requires Kubernetes and a message broker, making it heavier for simple prototypes.

The two approaches are complementary. An agent built with LangGraph or CrewAI can
run inside an Asya actor — the framework handles in-process tool orchestration
while Asya handles distributed execution, scaling, and fault tolerance.

## Comparison Table

| Dimension | 🎭 Asya | LangGraph | CrewAI | Google ADK | AutoGen | KAgent |
|---|---|---|---|---|---|---|
| **Maturity** | 🟡 Alpha | 🟢 GA | 🟢 GA | 🟡 Beta | 🟢 GA | 🟡 CNCF Sandbox |
| **Execution model** | Distributed actors via message queues | In-process state graph | In-process task pipeline | In-process agent tree | In-process pub/sub agents | K8s-native agent pods |
| **Language** | Python handlers, Go infra | Python | Python | Python, TS, Go, Java | Python | Go, Python |
| **Scaling** | Per-actor via KEDA (0-N pods) | Single process | Single process | Single process (Vertex AI for hosting) | Single process (gRPC distributed optional) | K8s HPA per agent |
| **Scale to zero** | 🟢 KEDA-driven per actor | 🔴 | 🔴 | 🟡 Vertex AI only (vendor-locked) | 🔴 | 🟡 Possible via KEDA add-on |
| **Failure isolation** | 🟢 Per actor (queue buffers on crash) | 🔴 Whole graph fails | 🔴 Whole crew fails | 🔴 Whole agent tree fails | 🟡 Per agent (distributed runtime) | 🟢 Per pod |
| **Handler lock-in** | 🟢 None — plain `dict -> dict` | 🔴 LangChain `@tool` + `TypedDict` state | 🔴 `@tool` decorator + Pydantic models | 🟡 Plain functions, but Gemini-oriented | 🔴 `AssistantAgent` classes + `FunctionTool` | 🟡 CRD-defined, early API |
| **State management** | Payload enrichment + state proxy (S3/Redis) | TypedDict with `Annotated` reducers + checkpointers | Flow state (Pydantic) + ChromaDB/SQLite | Session state dict with prefix scoping (`app:`, `user:`, `temp:`) | Chat history + ListMemory/ChromaDB/Redis | CRD-defined state |
| **Streaming** | FLY events via SSE (distributed) | 🟢 5 modes: values, updates, messages, events, custom writer | Event bus with `BaseEventListener` | Async generator events (`_run_async_impl`) | `run_stream()` with typed events | 🔴 Not yet |
| **Human-in-the-loop** | 🟢 Pause/resume via S3 checkpoint (x-pause/x-resume) | 🟢 `interrupt()` with checkpointer | 🔴 Manual (no built-in) | 🟡 Transfer to human agent | 🟡 Manual or handoff-based | 🔴 Not yet |
| **Dynamic routing** | 🟢 Actors rewrite `route.next` at runtime | 🟢 Conditional edges | 🟢 `@router` decorator | 🟢 Sub-agent delegation | 🟢 Handoffs + Swarm teams | 🟡 Static graph |
| **Multi-agent patterns** | Sequential, fan-out/fan-in via Flow DSL | Supervisor, subgraphs | Sequential, hierarchical crews | SequentialAgent, ParallelAgent, LoopAgent | RoundRobin, Selector, Swarm, MagenticOne | Multi-agent graph |
| **K8s native** | 🟢 CRD + Crossplane + KEDA | 🔴 | 🔴 | 🔴 (Vertex AI is GCP-native) | 🔴 | 🟢 CRD-based |
| **Transport** | SQS, RabbitMQ, GCP Pub/Sub | In-memory (or LangGraph Platform) | In-memory | In-memory (or Vertex AI) | In-memory (or gRPC distributed) | gRPC / in-cluster |
| **Protocol support** | 🟢 A2A + MCP gateway | 🔴 | 🔴 | 🟡 A2A support planned | 🔴 | 🟡 A2A planned |

## Key Differences

**In-process vs distributed execution.** Every framework above (except KAgent)
runs agents in a single process. Asya decomposes agents into separate pods
connected by queues. This enables per-agent scaling, fault isolation, and
independent deployment, but adds latency (queue hop per step) and operational
complexity (requires K8s + message broker).

**No SDK, no lock-in.** Asya handlers are plain Python functions (`dict -> dict`).
No base classes, no decorators, no framework imports. The survey of 14 frameworks
confirms every other framework requires either a decorator (`@tool`), a base
class (`BaseTool`, `AssistantAgent`), or a typed wrapper (`FunctionTool`). A
handler from any framework can be wrapped in a one-line function and deployed as
an Asya actor.

**State: enrichment vs reducers vs session dicts.** Frameworks use three state
patterns: LangGraph accumulates via typed reducers (`Annotated[list, add]`), ADK
writes to shared session state via `output_key`, and CrewAI/AutoGen thread state
through chat history. Asya's envelope payload is the state — each actor enriches
it and passes it downstream. For persistent cross-invocation state, the state
proxy provides a virtual filesystem backed by S3/Redis.

**Streaming architecture.** LangGraph offers the richest in-process streaming
(5 modes including custom `get_stream_writer()`). Asya's FLY events are simpler
but work across distributed actors — a token streamed from a GPU pod reaches the
client via SSE without the handler knowing about networking.

**Infrastructure as configuration.** Retry policies, timeouts, scaling thresholds,
and error routing are declared in the AsyncActor manifest (YAML), not in
application code. Platform engineers own infrastructure; data scientists own
handler logic.

## When to Use What

**Use 🎭 Asya when:**

- You run on Kubernetes and need per-step independent scaling
- GPU workloads must scale to zero between batches
- Multiple teams own different pipeline steps independently
- You need fault isolation — one failing agent must not stall the pipeline
- You want A2A + MCP protocol support out of the box

**Use LangGraph when:**

- You need rapid prototyping of complex agent graphs with conditional logic
- Sub-second latency between steps matters
- You want the richest streaming (5 modes) and checkpointing ecosystem
- Your deployment target is LangGraph Platform (managed)

**Use CrewAI when:**

- You want role-based multi-agent collaboration with minimal code
- Decorator-driven agent definition (`@start`, `@listen`, `@router`) fits your style
- The workload fits in a single process

**Use Google ADK when:**

- You are building on Google Cloud / Vertex AI
- You need the `output_key` enrichment pattern for multi-agent state sharing
- Multi-language support matters (Python, TS, Go, Java)

**Use AutoGen when:**

- You need flexible multi-agent conversation patterns (round-robin, selector, swarm)
- The gRPC distributed runtime fits your scale requirements
- Research-oriented agent architectures with rich memory (ChromaDB, Redis) are the goal

**Use KAgent when:**

- You want a CNCF-aligned, K8s-native agent runtime
- You prefer CRD-defined agent graphs over code-first workflows
- You are evaluating early-stage projects and can tolerate API changes
