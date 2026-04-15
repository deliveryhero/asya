---
title: "ADR: MCP and A2A Are Siblings, Not Layers"
status: accepted
date: 2026-04-14
---

# ADR: MCP and A2A Are Siblings, Not Layers

## Context

Early gateway design treated MCP and A2A as potentially overlapping -- a flow
could be exposed as both an MCP tool and an A2A agent. This was confusing:
should a training pipeline be a tool or an agent? Could a client start via MCP
and subscribe via A2A?

Research revealed MCP and A2A are fundamentally different protocols:

| MCP has, A2A doesn't | A2A has, MCP doesn't |
|---|---|
| Tool discovery (JSON Schema) | Task state machine |
| Resources, prompts, sampling | Conversation history |
| Log notifications (data field) | Push notifications |
| | Pause/resume (input_required) |

MCP Tasks (experimental, spec 2025-11-25) partially converges with A2A's task
model but is not yet stable.

## Decision

**MCP and A2A are siblings, not layers.** Both are protocol adapters over /mesh/.
Neither is a subset of the other. A flow declares ONE protocol:

- **MCP**: deterministic tool calls. "Execute X with params, return result."
  Training pipelines, deployments, queries.
- **A2A**: conversational agents. "Work on this problem, iterate with me."
  Research orchestrators, iterative agents.

## Consequences

- Each flow in flows.yaml declares `protocol: mcp` or `protocol: a2a` (not both)
- MCP flows get tool schemas, progress notifications
- A2A flows get task state, history, pause/resume, artifact streaming
- Dashboard uses /mesh/ (neither protocol)
- Clear guidance for users on which protocol to choose

## Alternatives Considered

- **Allow both protocols per flow**: confusing, no real use case for mixing
- **A2A as superset**: loses MCP-specific features (schemas, resources)
- **MCP-only, ignore A2A**: loses conversational/agentic patterns
