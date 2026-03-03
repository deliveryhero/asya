---
title: Wire a2a-go handler with Agent Card and endpoint layout
priority: 2 # medium
type: task
tags:
  - pr:257
dependencies:
  - 1c0d/1qn6p7
  - 1c0d/1qx70r
---


## Summary

Wire `a2asrv.NewHandler()` and `a2asrv.NewJSONRPCHandler()` from `a2a-go`
v0.3.7 into `cmd/gateway/main.go`, reorganize the endpoint layout into three
namespaces, serve the Agent Card at `/.well-known/agent.json`, and remove the
old hand-rolled A2A handler code from Phase 1 (PR #202).

Reference: RFC Section 6.1 (Endpoint Layout), Section 6.2 (a2a-go Library
Integration), Section 8.1 (Agent Card Structure), Appendix B (Server
Integration).

## Endpoint Layout (RFC Section 6.1)

Reorganize all gateway routes into three namespaces under a configurable base
prefix:

```
{base}/a2a/*   — A2A protocol endpoints (via a2a-go handler)
{base}/mcp/*   — MCP endpoints (existing, moved from current paths)
{base}/mesh/*  — Internal sidecar-facing endpoints (already at /mesh/ via 1mx1)
```

Plus two root-level endpoints (not affected by base prefix):
- `GET /.well-known/agent.json` — Agent Card discovery (A2A spec requirement)
- `GET /health` — Kubernetes health probes

### Base prefix configuration

- Env var: `ASYA_BASE_PREFIX` (default: empty string)
- Example: `ASYA_BASE_PREFIX="/api/v1"` produces `/api/v1/a2a/...`,
  `/api/v1/mcp/...`, `/api/v1/mesh/...`

### A2A namespace wiring

Mount `a2asrv.NewJSONRPCHandler()` for JSON-RPC endpoints and
`a2asrv.NewHandler()` for REST endpoints:

```go
a2aHandler := a2asrv.NewHandler(executor, a2asrv.WithTaskStore(a2aStore))
jsonRPCHandler := a2asrv.NewJSONRPCHandler(a2aHandler)

mux.Handle(a2aPrefix+"/message:send", jsonRPCHandler)
mux.Handle(a2aPrefix+"/message:stream", jsonRPCHandler)
mux.Handle(a2aPrefix+"/tasks/", a2aHandler)
mux.Handle(a2aPrefix+"/extendedAgentCard", a2aHandler)
```

### MCP namespace

Move existing MCP endpoints under `{base}/mcp`:
- `{base}/mcp` — MCP Streamable HTTP (POST)
- `{base}/mcp/sse` — MCP SSE deprecated (GET)
- `{base}/mcp/tools/call` — REST tool invocation (POST)

## Agent Card (RFC Section 8.1)

### Generation

Build the `a2a.AgentCard` struct dynamically from the tool registry:
- Query tools table filtered by `WHERE a2a_enabled = true`
- Map each tool to an `a2a.AgentSkill` with `id`, `name`, `description`,
  `tags`, `inputModes`, `outputModes`, `examples`
- Populate card-level fields from env vars

### Env vars

| Env Var | Purpose | Default |
|---------|---------|---------|
| `ASYA_A2A_NAME` | Agent name in card | `"Asya Gateway"` |
| `ASYA_A2A_DESCRIPTION` | Agent description | `"AI Actor Mesh"` |
| `ASYA_A2A_VERSION` | Agent version | Build version |
| `ASYA_A2A_PUBLIC_URL` | Base URL for `supportedInterfaces` | Required |

### Serving

Serve at root path via `a2asrv.NewStaticAgentCardHandler(agentCard)`:

```go
mux.Handle("/.well-known/agent.json", a2asrv.NewStaticAgentCardHandler(agentCard))
```

This is always at root, not affected by `ASYA_BASE_PREFIX` (per A2A spec).

### Refresh (RFC Section 8.4.4)

The Agent Card must be regenerated whenever the tool registry mutates
(POST/DELETE on `/mesh/expose`). Implement via atomic pointer swap:
- After each registry mutation, rebuild the `AgentCard` struct from the
  updated tool list
- Store via `atomic.Pointer[a2a.AgentCard]` for lock-free reads
- Use `a2asrv.NewAgentCardHandler(producer)` with a producer function that
  reads from the atomic pointer, so the card handler always serves the latest
  version

## Removal of Old A2A Code

Remove the hand-rolled A2A handler code introduced in Phase 1 (PR #202):
- `internal/a2a/handler.go` — custom JSON-RPC dispatch (replaced by a2a-go)
- `internal/a2a/types.go` — hand-rolled A2A types (replaced by `a2a` package)
- Any custom SSE formatting or request validation logic now handled by a2a-go
- Update imports throughout the gateway to use `a2a-go` types

## Files

- `src/asya-gateway/cmd/gateway/main.go` — endpoint wiring and handler setup
- `src/asya-gateway/internal/a2a/agent_card.go` — Agent Card generation and
  atomic refresh logic
- `src/asya-gateway/internal/a2a/agent_card_test.go` — unit tests
- `src/asya-gateway/internal/a2a/handler.go` — remove (replaced by a2a-go)
- `src/asya-gateway/internal/a2a/types.go` — remove (replaced by a2a-go)

## Testing

Unit tests for Agent Card generation (`agent_card_test.go`):
- Card includes only skills where `a2a_enabled = true`
- Card excludes tools where `a2a_enabled = false`
- Card populates `name`, `description`, `version` from env vars
- Card `supportedInterfaces` uses `ASYA_A2A_PUBLIC_URL`
- Card regenerates on registry mutation (atomic pointer swap)
- Empty skill list produces valid card with empty `skills` array
- Skill fields map correctly: tool `name` -> skill `id`, tool `description`
  -> skill `description`, tool `a2a_tags` -> skill `tags`, etc.

## Dependencies

- T3 (`1c0d/1qn6p7`): Tool registry for reading skills and triggering card refresh
- T6 (`1c0d/1qx70r`): Executor to pass into `a2asrv.NewHandler()`
