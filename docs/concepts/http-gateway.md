# HTTP Gateway

The actor mesh is asynchronous by design — messages flow through queues, and
results arrive eventually. The HTTP gateway bridges this async world with
synchronous HTTP clients that expect request-response semantics.

## What it does

The gateway accepts HTTP requests, injects envelopes into the mesh, and waits
for results. It supports three protocols:

| Protocol | Audience | Use case |
|----------|----------|----------|
| **A2A** (Agent-to-Agent) | AI agents, orchestrators | Multi-turn agent communication with task lifecycle |
| **MCP** (Model Context Protocol) | LLM clients, developers | Tool invocation from LLMs like Claude or GPT |
| **REST** | Any HTTP client | Simple request-response over `/mcp/` endpoints |

## Two deployment modes

The gateway runs as a single binary in one of two modes:

- **api** — handles external traffic (A2A, MCP, REST). Exposed via Ingress or
  LoadBalancer
- **mesh** — handles internal sidecar callbacks (progress, FLY events, final
  results). Cluster-internal only

Both modes share the same PostgreSQL database for task state.

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

This enables interoperability with any A2A-compliant agent framework.

## Further reading

- [Gateway component reference](../reference/components/core-gateway.md) —
  architecture, configuration, environment variables
- [Gateway API specification](../reference/specs/gateway-api.md) — endpoint
  reference, request/response formats
- [Gateway setup guide](../setup/guide-gateway.md) — deployment, TLS,
  PostgreSQL configuration
