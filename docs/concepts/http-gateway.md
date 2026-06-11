---
description: "HTTP gateway: bridges async actor mesh with synchronous HTTP, A2A protocol, MCP tools"
---

# HTTP Gateway

The actor mesh is asynchronous by design — messages flow through queues, and
results arrive eventually. The HTTP gateway bridges this async world with
synchronous HTTP clients that expect request-response semantics.

## What it does

The gateway accepts HTTP requests, injects envelopes into the mesh, and waits
for results. Endpoints are organized into three namespaces:

| Namespace | Protocol | Audience | Example |
|-----------|----------|----------|---------|
| `/a2a/` | A2A (Agent-to-Agent) | AI agents, orchestrators | `POST /a2a/` — SendMessage |
| `/mcp` | MCP (Model Context Protocol) | LLM clients, developers | `POST /mcp` — tool invocation |
| `/api/v1/mesh/` | REST (internal) | Sidecars, operators | `POST /api/v1/mesh/{id}/events` — status/FLY callbacks |

Special root routes: `/.well-known/agent.json` (A2A Agent Card discovery) and
`/health` (K8s liveness/readiness probe).

## Split containers

The gateway is one image (`asya-gateway`) that ships several binaries, each running
as a container in a single pod:

- **mesh-api** — core HTTP server: task CRUD, SSE, queue publish, and the internal
  `/api/v1/mesh/` callbacks from sidecars
- **mcp-adapter** — MCP HTTP, backed by mesh-api
- **a2a-adapter** — A2A JSON-RPC, backed by mesh-api
- **state-proxy-mesh** — task state sidecar

Task state is pluggable: PostgreSQL (`pg-kv`, default) or local files / in-memory
(`pvc-kv`, no database required).

## Real-time streaming

Clients can subscribe to Server-Sent Events (SSE) for real-time updates:

- **FLY events** — streaming tokens, live progress from actors
- **Status transitions** — pending, working, completed, failed
- **A2A task updates** — full A2A protocol subscription support

## A2A task lifecycle

The gateway maps internal mesh states to A2A protocol states:

| Mesh status | A2A state |
|-------------|-----------|
| `pending` | `submitted` |
| `running` | `working` |
| `succeeded` | `completed` |
| `paused` | `input_required` |
| `failed` | `failed` |
| `canceled` | `canceled` |
| `auth_required` | `auth_required` |

This enables interoperability with any A2A-compliant agent framework.

## Further reading

- [Gateway component reference](../reference/components/core-gateway.md) —
  architecture, configuration, environment variables
- [Gateway API specification](../reference/specs/gateway-api.md) — endpoint
  reference, request/response formats
- [Gateway setup guide](../setup/guide-gateway.md) — deployment, TLS,
  state backend configuration
