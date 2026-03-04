# Asya🎭 Gateway

MCP (Model Context Protocol) gateway for async actors. JSON-RPC 2.0 server with PostgreSQL job storage and SSE streaming.

## Quick Start

```bash
# Kubernetes (Helm)
helm install asya-gateway deploy/helm-charts/asya-gateway \
  -n asya --create-namespace

# Standalone
export ASYA_DATABASE_URL="postgresql://user:pass@localhost:5432/asya"
export ASYA_RABBITMQ_URL="amqp://guest:guest@localhost:5672/"
go run cmd/gateway/main.go
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_DATABASE_URL` | PostgreSQL connection string | `""` (uses in-memory store) |
| `ASYA_GATEWAY_PORT` | HTTP server port | `"8080"` |
| `ASYA_RABBITMQ_URL` | RabbitMQ connection URL | `"amqp://guest:guest@localhost:5672/"` |
| `ASYA_RABBITMQ_EXCHANGE` | RabbitMQ exchange name | `"asya"` |

## API Endpoints

### MCP Protocol Endpoints

| Endpoint | Transport | Description |
|----------|-----------|-------------|
| `POST /mcp` | Streamable HTTP | MCP JSON-RPC 2.0 endpoint (recommended) |
| `/mcp/sse` | SSE | MCP endpoint via SSE transport (deprecated, for backward compatibility) |

### Task Management Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /tools/call` | REST tool invocation (simple JSON API) |
| `POST /mesh/expose` | Register or update a tool/skill |
| `GET /mesh/expose` | List all registered tools/skills |
| `GET /mesh/{id}` | Envelope status |
| `GET /mesh/{id}/stream` | SSE envelope updates |
| `POST /mesh/{id}/progress` | Sidecar progress update |
| `POST /mesh/{id}/final` | End actor final status |
| `GET /health` | Health check |

## Tool Registration

Tools are registered dynamically via the `/mesh/expose` REST API and stored in PostgreSQL.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mesh/expose` | `POST` | Register or update a tool/skill (upsert) |
| `/mesh/expose` | `GET` | List all registered tools/skills |

## Database

PostgreSQL with Sqitch migrations. See [db/README.md](./db/README.md) for setup.

## Full Documentation

See [docs/architecture/asya-gateway.md](../../docs/architecture/asya-gateway.md)
