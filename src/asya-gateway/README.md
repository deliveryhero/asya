# Asya Gateway

MCP (Model Context Protocol) gateway for the Asya async actor framework. Built with the official [MCP Go SDK](https://github.com/modelcontextprotocol/go-sdk), the gateway exposes MCP tools via JSON-RPC 2.0, manages job state with PostgreSQL, and provides real-time job streaming via Server-Sent Events (SSE).

## Features

- **MCP JSON-RPC 2.0 Server**: Implements Model Context Protocol using the official Go SDK
- **Configurable Tools**: Define tools in YAML without code changes (see [config/README.md](config/README.md))
- **Type-safe Tool Registration**: SDK's `mcp.AddTool()` with JSON schema validation
- **Job State Management**: PostgreSQL-backed persistent job storage
- **Real-time Streaming**: SSE support for job progress updates
- **Queue Integration**: RabbitMQ message queue support
- **Kubernetes-style Job Status**: Pending → Running → Succeeded/Failed
- **Timeout Management**: Automatic job timeout with deadline tracking
- **Database Migrations**: Sqitch-based schema evolution

## Architecture

```
┌─────────────┐
│   Client    │
│  (MCP CLI)  │
└──────┬──────┘
       │ JSON-RPC 2.0
       ▼
┌─────────────────────────────────────┐
│        Asya Gateway                  │
│  ┌──────────────┐  ┌─────────────┐ │
│  │  MCP Server  │  │  Job Store  │ │
│  │  (handlers)  │  │ (PostgreSQL)│ │
│  └──────┬───────┘  └──────┬──────┘ │
└─────────┼──────────────────┼────────┘
          │                  │
          ▼                  ▼
    ┌──────────┐      ┌──────────┐
    │ RabbitMQ │      │PostgreSQL│
    │  Queues  │      │ Database │
    └──────────┘      └──────────┘
```

## Quick Start

### Kubernetes Deployment

```bash
# Install with bundled PostgreSQL
helm install asya-gateway deploy/helm-charts/asya-gateway \
  --namespace asya \
  --create-namespace

# Or use helmfile (recommended)
cd examples/deployment-minimal
helmfile sync
```

See [Helm Chart README](../../deploy/helm-charts/asya-gateway/README.md) and [Database Migrations README](./db/README.md) for details.

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_CONFIG_PATH` | Tool config file/directory | `""` (uses hardcoded tools) |
| `ASYA_DATABASE_URL` | PostgreSQL connection string | `""` (uses in-memory store) |
| `ASYA_GATEWAY_PORT` | HTTP server port | `"8080"` |
| `ASYA_RABBITMQ_URL` | RabbitMQ connection URL | `"amqp://guest:guest@localhost:5672/"` |
| `ASYA_RABBITMQ_EXCHANGE` | RabbitMQ exchange name | `"asya"` |

## API Endpoints

- **POST `/mcp`** - MCP JSON-RPC 2.0 endpoint
- **GET `/jobs/{id}`** - Get job status
- **GET `/jobs/{id}/stream`** - SSE stream of job updates
- **GET `/jobs/{id}/active`** - Check if job is active (for actors)
- **POST `/jobs/{id}/heartbeat`** - Actor heartbeat
- **GET `/health`** - Health check

## Database

The gateway uses PostgreSQL for persistent job storage with two main tables:

- **jobs**: Job metadata and current state
- **job_updates**: Audit log for SSE streaming

Migrations are managed with Sqitch. See [db/README.md](./db/README.md) for details.

## License

See repository root for license information.
