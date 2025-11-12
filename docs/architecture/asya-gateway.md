# Asya🎭 Gateway

MCP (Model Context Protocol) gateway for async actors.

> **Full Documentation**: [src/asya-gateway/README.md](../../src/asya-gateway/README.md)

## Overview

JSON-RPC 2.0 server exposing MCP tools, with PostgreSQL envelope storage and SSE streaming.

## Key Features

- Dual MCP transport support:
  - **Streamable HTTP** (recommended, per MCP specification)
  - **SSE** (deprecated, for backward compatibility)
- MCP tool calls via JSON-RPC 2.0
- Configurable tools via YAML (see [config/README.md](../../src/asya-gateway/config/README.md))
- PostgreSQL envelope storage
- Real-time SSE streaming for envelope updates
- RabbitMQ integration
- Kubernetes-style envelope status (pending → running → succeeded/failed)

## Quick Start

```bash
# Kubernetes
helm install asya-gateway deploy/helm-charts/asya-gateway -n asya --create-namespace

# Standalone
export ASYA_DATABASE_URL="postgresql://user:pass@localhost:5432/asya"
export ASYA_RABBITMQ_URL="amqp://guest:guest@localhost:5672/"
go run src/asya-gateway/cmd/gateway/main.go
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_CONFIG_PATH` | `""` | Tool config file/directory |
| `ASYA_DATABASE_URL` | `""` | PostgreSQL connection |
| `ASYA_GATEWAY_PORT` | `"8080"` | HTTP port |
| `ASYA_RABBITMQ_URL` | `"amqp://guest:guest@localhost:5672/"` | RabbitMQ |
| `ASYA_RABBITMQ_EXCHANGE` | `"asya"` | Exchange name |

## API Endpoints

### MCP Protocol Endpoints

- `POST /mcp` - Streamable HTTP transport (recommended)
- `/mcp/sse` - SSE transport (deprecated, for backward compatibility)
- `POST /tools/call` - REST tool invocation (simple JSON API)

### Envelope Management Endpoints

- `GET /envelopes/{id}` - Envelope status
- `GET /envelopes/{id}/stream` - SSE envelope updates
- `POST /envelopes/{id}/progress` - Sidecar progress update
- `POST /envelopes/{id}/final` - End actor final status
- `GET /health` - Health check

## Envelope Lifecycle

1. Client calls MCP tool → Gateway creates envelope
2. Envelope: pending → running (actor picks up)
3. Sidecar sends progress updates
4. End actor reports final status
5. Client streams updates via SSE

## Transport Selection

**Recommended**: Use streamable HTTP transport (`POST /mcp`) per MCP specification.

**Backward Compatibility**: SSE transport (`/mcp/sse`) is available for older clients but is deprecated.

Both transports support the same MCP methods:
- `initialize` - Protocol handshake
- `tools/list` - List available tools
- `tools/call` - Invoke a tool

## Full Documentation

- [src/asya-gateway/README.md](../../src/asya-gateway/README.md) - Complete reference
- [src/asya-gateway/config/README.md](../../src/asya-gateway/config/README.md) - Tool configuration
- [src/asya-gateway/db/README.md](../../src/asya-gateway/db/README.md) - Database setup

## Next Steps

- [Sidecar Component](asya-sidecar.md)
- [Runtime Component](asya-runtime.md)
- [Deployment Guide](../guides/deploy.md)
