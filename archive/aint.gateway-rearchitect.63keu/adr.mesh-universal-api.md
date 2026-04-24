---
title: "ADR: /mesh/ as Universal API, Unified /events Endpoint"
status: accepted
date: 2026-04-16
supersedes: "ADR: /mesh/ as the Universal Asya API"
---

# ADR: /mesh/ as Universal API, Unified /events Endpoint

## Context

The gateway previously exposed /mcp/*, /a2a/*, and /mesh/* as separate API
surfaces. MCP and A2A overlapped with /mesh/ (all create messages, subscribe
to events, query status). Dashboard and CLI had to choose a protocol even when
they just wanted to interact with the mesh.

Additionally, the internal API had separate endpoints for different event types
(/progress, /final, /fly, /active) adding surface area.

## Decision

**`/api/v1/mesh/` is the universal Asya-native API.** MCP and A2A are optional
protocol adapters (separate binaries) that translate to /mesh/ calls.

Routes:
```
POST   /api/v1/mesh/?actor={name}     Create message
GET    /api/v1/mesh/{id}              Message status
GET    /api/v1/mesh/{id}/events       Subscribe (SSE)
POST   /api/v1/mesh/{id}/events       Publish event (sidecar)
DELETE /api/v1/mesh/{id}              Cancel
GET    /api/v1/mesh/                  List messages
```

**Unified /events endpoint**: GET subscribes (SSE consumer), POST publishes
(sidecar producer). Same resource path, different HTTP methods. Replaces
separate /progress, /final, /fly, /active endpoints. Event type differentiated
by `type` field in POST body (status, fly).

Sidecar heartbeat/cancel check: `GET /api/v1/mesh/{id}` returns current status.
If canceled/paused, sidecar stops processing. Same endpoint as external status
query (different port for security).

## Consequences

- 5 external routes + 2 internal routes (down from ~12)
- Dashboard, CLI, and custom clients use /mesh/ directly
- Protocol adapters call /mesh/ as HTTP clients (stateless)
- One event publishing endpoint for all sidecar callback types
- No /active endpoint -- sidecar checks status field from GET /mesh/{id}
