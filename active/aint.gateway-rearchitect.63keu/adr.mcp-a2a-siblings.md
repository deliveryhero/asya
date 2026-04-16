---
title: "ADR: MCP and A2A Are Siblings, Not Layers"
status: accepted
date: 2026-04-16
---

# ADR: MCP and A2A Are Siblings, Not Layers

## Context

Early gateway design allowed a flow to be exposed as BOTH an MCP tool and an
A2A agent simultaneously. This was confusing: should a training pipeline be a
tool or an agent? Could a client start via MCP and subscribe via A2A?

Research revealed MCP and A2A are fundamentally different protocols for
different interaction patterns:

| MCP has, A2A doesn't | A2A has, MCP doesn't |
|---|---|---|
| Tool discovery (JSON Schema) | Task state machine (9 states) |
| Resources, prompts, sampling | Conversation history |
| Log notifications (data field) | Push notifications |
| | Pause/resume (input_required) |
| | Rich artifact streaming |

MCP = deterministic tool calls. A2A = conversational agents.

## Decision

**MCP and A2A are siblings, not layers.** Both are protocol adapters over
/mesh/. Neither is a subset of the other. A flow declares ONE protocol
(via `asya expose --as mcp` or `asya expose --as a2a`).

- MCP flows: training pipelines, deployments, queries, metrics
- A2A flows: research orchestrators, iterative agents, human-in-the-loop

## Consequences

- `asya expose --as mcp|a2a` configures the corresponding adapter only
- MCP and A2A adapters are separate binaries, separate ConfigMaps
- Dashboard uses /mesh/ directly (neither protocol)
- Clear guidance for users: structured params -> MCP, conversational -> A2A
- Future protocols (MCP Tasks when stable, others) add new adapters
