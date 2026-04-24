---
description: "Agentic patterns: AI agent swarms as distributed actors with streaming, pause/resume, fan-out"
---

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
    for chunk in llm.stream(payload["prompt"]):
        yield "FLY", {"chunk": chunk}  # partial update, flies via HTTP directly to Gateway
    yield {"response": llm.result()}   # regular response to the next actor
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

The [HTTP Gateway](http-gateway.md) exposes agents via standard A2A and MCP
protocols. Your agents run as actors on the mesh — each with independent scaling,
fault isolation, and queue-based communication. External AI agents and LLM clients
(Claude, GPT) interact with the mesh through these standard protocols, rather than
through framework-specific integrations.

## Example: evaluator-optimizer loop

A classic agentic pattern — a generator produces output, an evaluator scores it,
and the loop repeats until quality thresholds are met:

```python
@flow
async def evaluator_optimizer(state: dict) -> dict:
    state["iteration"] = 0

    while True:
        state["iteration"] += 1
        state = await generator(state)
        state = await evaluator(state)

        if state.get("score", 0) >= SCORE_THRESHOLD:
            break
        if state["iteration"] >= MAX_ITERATIONS:
            break

    state = await polisher(state)
    return state
```

The flow compiler transforms this into a distributed actor graph:

<p align="center">
<a href="/docs/website/img/agentic-evaluator-optimizer.png" target="_blank" title="Click to view full size">
  <img src="/docs/website/img/agentic-evaluator-optimizer.png" alt="Evaluator-optimizer flow: generator-evaluator loop with score threshold" style="max-width: 60%; cursor: zoom-in;"/>
</a>
</p>
<p align="center"><em>Each box is an independent actor. The loop runs as message-passing between queues.</em></p>

More agentic flow examples in [examples/end-to-end/monorepo/agentic](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo/src/agentic/flows):
[human-in-the-loop](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/agentic/flows/flow_human_in_the_loop.py),
[orchestrator-workers](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/agentic/flows/flow_orchestrator_workers.py),
[multi-agent debate](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/agentic/flows/flow_multi_agent_debate.py).


## Further reading

- [Agentic Patterns guide](../usage/guide-agentic-patterns.md) — routing
  patterns, tool use, multi-turn agents
- [Streaming guide](../usage/guide-streaming.md) — FLY event protocol and SSE
  integration
- [Pause/Resume guide](../usage/guide-pause-resume.md) — checkpoint and restore
  workflow
