# Agentic Native

The actor mesh is the most general agentic pattern: each AI agent runs as an
independent actor with its own scaling, failure isolation, and queue. Agent
swarms become distributed systems with all the operational properties of the
mesh.

## Agents as actors

Each agent in an Asya mesh is a standard actor — a stateless pod with a handler
function. The agent's LLM calls, tool use, and decision-making live in the
handler. The mesh provides everything else: message delivery, retries, scaling,
and observability.

This means agent swarms get the same operational properties as any other actor
pipeline:

- Independent scaling per agent (GPU agents scale differently from routing
  agents)
- Failure isolation — one agent crashing does not affect others
- Durable message delivery — no lost work on pod eviction

## Real-time streaming with FLY events

Actors can stream intermediate results to connected clients via FLY events:

```python
def handler(payload: dict):
    for token in llm.stream(payload["prompt"]):
        yield "FLY", {"token": token}
    yield {"response": llm.result()}
```

FLY events are ephemeral — they reach only currently connected SSE clients. For
data that must survive across pipeline stages, use `payload` instead.

## Pause and resume for human-in-the-loop

An agent can pause execution and wait for human input:

1. The agent routes to `x-pause`, which checkpoints the full envelope to S3
2. The gateway reports `input_required` to the client
3. The human provides input via the API
4. `x-resume` restores the envelope, merges the new input, and re-injects into
   the mesh

The pipeline continues from exactly where it stopped. No state is lost.

## Virtual memory for agents

Agents that need persistent memory (conversation history, tool results) use the
[state proxy](virtual-actors.md). The agent reads and writes files under
`/state/` — the proxy persists them to S3, Redis, or another backend. The agent
remains a stateless Deployment.

## Interoperability

The [HTTP Gateway](http-gateway.md) exposes agents via A2A and MCP protocols,
enabling integration with external agent frameworks (Google ADK, LangGraph,
Mastra) and LLM clients (Claude, GPT).

## Further reading

- [Agentic Patterns guide](../usage/guide-agentic-patterns.md) — routing
  patterns, tool use, multi-turn agents
- [Streaming guide](../usage/guide-streaming.md) — FLY event protocol and SSE
  integration
- [Pause/Resume guide](../usage/guide-pause-resume.md) — checkpoint and restore
  workflow
