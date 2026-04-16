---
title: "Phase 3: MCP adapter (asya-mcp-adapter)"
status: open
priority: 1 # high
dependencies:
  - nacr7
---

MCP Streamable HTTP adapter that translates MCP protocol to /mesh/ API calls. ~300-500 LOC Go.

Library: mark3labs/mcp-go

MCP operations:
- initialize: MCP handshake
- tools/list: return tool definitions from ConfigMap
- tools/call: two-step (POST /mesh/?actor=X local + GET /mesh/{id}/events via Ingress)
- Translate mesh SSE -> MCP events:
  - status event -> notifications/progress (% + message text)
  - fly event -> notifications/message (log with data field)
  - terminal status -> CallToolResult (final)
- Return as text/event-stream (MCP Streamable HTTP)

Implementation:
- cmd/mcp-adapter/main.go
- internal/mcp/ — MCP handler using mark3labs/mcp-go
- internal/watcher/ — ConfigMap polling watcher (shared code)
- Two env vars: MESH_API_URL (localhost:8080), MESH_INGRESS_URL (External Ingress)
- Reads tool definitions from /etc/asya/mcp/ (mounted ConfigMap)

ConfigMap schema (asya-mcp-tools):
  tools:
  - name: train_model
    description: 'Train a model'
    actor: start-my-flow
    timeout: 3600
    inputSchema: {type: object, properties: {lr: {type: number}}}
    progress: true

Testing:
- Unit: MCP handler, tool registry, event translation
- Component: Docker Compose with mesh-api + PG + MQ, test tools/list + tools/call
- E2E: Kind cluster, full MCP flow from client to actor and back
- Docs: docs/usage/guide-gateway.md (MCP vs A2A guide)

Depends on: nacr7 (mesh-api)
