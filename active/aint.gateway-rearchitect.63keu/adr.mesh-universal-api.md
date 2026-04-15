---
title: "ADR: /mesh/ as the Universal Asya API"
status: accepted
date: 2026-04-14
---

# ADR: /mesh/ as the Universal Asya API

## Context

The current gateway exposes three API surfaces: `/mcp/*`, `/a2a/*`, and
`/mesh/*`. The `/mesh/` endpoints were initially internal-only (sidecar
callbacks). MCP and A2A each had their own external endpoints with overlapping
functionality (both create tasks, subscribe to events, query status).

This created confusion: which endpoint should a dashboard use? A CLI? A custom
integration? Each client needed to choose a protocol even when they just wanted
to create a task and watch it.

## Decision

**`/mesh/` is the universal Asya-native API.** MCP and A2A are optional protocol
adapters on top of /mesh/. Any client can use /mesh/ directly.

`/mesh/` is exposed externally (port 8080, authenticated) for reads + create.
Sidecar write endpoints remain internal-only (port 8081, NetworkPolicy).

## Consequences

- Dashboard, CLI, and custom integrations use /mesh/ directly (no protocol
  overhead)
- MCP adapter (agentgateway) translates tools/call -> POST /mesh/
- A2A adapter (dispatcher) translates tasks/send -> POST /mesh/
- One API to document, test, and monitor
- Security boundary is port-based, not path-based

## Alternatives Considered

- **Keep /mesh/ internal, expose /dispatch + /stream**: adds unnecessary
  renaming, fragments the API surface
- **MCP as universal, A2A on top**: MCP lacks task state, history, pause/resume
  -- not general enough
- **A2A as universal, MCP on top**: A2A lacks tool schemas, resources, sampling
  -- not general enough
