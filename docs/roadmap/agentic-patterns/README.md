# Agentic Patterns Roadmap

Gap analysis for Asya's agentic use-cases. Each pattern directory contains:
- `pattern.md` — use-case description, architecture, why Asya fits
- `missing.md` — concrete code-level gaps blocking the pattern, with file references

## Standalone Asya Patterns

These leverage Asya's unique properties (actor model, state-in-message, queue-based
choreography) for use-cases where no external agent framework is needed.

| Pattern | Core Asya Feature | Readiness |
|---|---|---|
| [Multi-Tenant Platform](multi-tenant-platform/) | Actor isolation, per-actor scaling | Medium |
| [Document Processing](document-processing/) | Fan-out/fan-in, map-reduce | Medium |
| [Adaptive RAG](adaptive-rag/) | While loops, fan-out retrievers | Medium |
| [Multi-Model Evaluation](multi-model-evaluation/) | Fan-out, voting/debate | Medium |
| [Long-Running Checkpointed](long-running-checkpointed/) | Durable queues, pause/resume | High |
| [Guardrailed Production](guardrailed-production/) | Try/except, safety sandwich | High |

## External Agent Integration Patterns

These describe how external agentic tools (Claude Code, Goose, Aider, ADK agents,
LangGraph agents, custom MCP/A2A clients) interact with Asya deployed on a
company's platform.

| Pattern | Integration Protocol | Readiness |
|---|---|---|
| [Agent MCP Backend](agent-mcp-backend/) | MCP tools/call | High |
| [Agent A2A Integration](agent-a2a-integration/) | A2A message/send | High |
| [Shared State Collaboration](shared-state-collaboration/) | State-proxy S3/GCS/Redis | Medium |
| [Async Background Processing](async-background-processing/) | A2A non-blocking + FLY SSE | High |

## Strategic Platform Pattern

| Pattern | Integration Protocol | Readiness |
|---|---|---|
| [Agentic Workbench Platform](enterprise-coding-platform/) | Workbench (SSH) + heartbeat actors + state-proxy | Medium |

Replace heavy static workbenches (JupyterLab) with a two-tier model: a
researcher's workbench pod (SSH, VS Code Remote, FUSE-mounted S3 datasets) +
ephemeral Asya actors for parallel research/compute. Actors follow the heartbeat
pattern — wake on message, read checkpoint from S3, do work, write results, die.
Simulates OpenClaw's session model but distributed and crash-safe. The #1 gap is
FUSE mount for state-proxy (use s3fs-fuse as pragmatic starting point).

## Cross-Cutting Gaps

These gaps affect multiple patterns:

1. **No crew actor library for agentic primitives** — every flow re-implements
   LLM calls, tool dispatch, memory, and validation from scratch
2. **No input/output schema extraction from flows** — MCP tool registration
   requires manual schema definition in ConfigMap YAML
3. **Max-iteration guard not enforced** — `FlowCompiler.max_iterations=100` is
   stored but never checked at compile or runtime
4. **Fan-in has no timeout or partial failure handling** — if one branch hangs,
   the entire fan-in blocks indefinitely
5. **No multi-turn conversation API** — clients cannot send follow-up messages
   to a running task; each message creates a new task
6. **Pause metadata not exposed via GetTask** — clients can't discover what
   input a paused task requires
