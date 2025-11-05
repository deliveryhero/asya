# Asya Gateway

MCP (Model Context Protocol) gateway for the Asya async actor framework.

> 📄 **Source Code**: [`src/asya-gateway/`](/src/asya-gateway/)
> 📖 **Developer README**: [`src/asya-gateway/README.md`](/src/asya-gateway/README.md)

## Overview

The gateway exposes MCP tools via JSON-RPC 2.0, manages job state with PostgreSQL, and provides real-time job streaming via Server-Sent Events (SSE).

## Features

- **MCP JSON-RPC 2.0 Server**: Implements the Model Context Protocol
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

## Configuration

Configure via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
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

Migrations are managed with Sqitch. See [`src/asya-gateway/db/README.md`](/src/asya-gateway/db/README.md) for details.

## Deployment

### Kubernetes (via Helm)

```bash
# Install with bundled PostgreSQL
helm install asya-gateway deploy/helm-charts/asya-gateway \
  --namespace asya \
  --create-namespace
```

See [Helm Chart README](../../deploy/helm-charts/asya-gateway/README.md) for configuration options.

### Standalone (Development)

```bash
cd src/asya-gateway

# Set environment
export ASYA_DATABASE_URL="postgresql://user:pass@localhost:5432/asya"
export ASYA_RABBITMQ_URL="amqp://guest:guest@localhost:5672/"

# Run migrations
sqitch deploy

# Start gateway
go run cmd/gateway/main.go
```

## Job Lifecycle

1. **Create Job**: Client calls MCP tool
2. **Pending**: Job created, waiting for actor
3. **Running**: Actor picks up job
4. **Heartbeat**: Actor sends periodic heartbeats
5. **Completed**: Actor finishes, job marked Succeeded/Failed
6. **Stream**: Clients can stream updates via SSE

## Key Components

### MCP Server (`internal/mcp/server.go`)
- Implements JSON-RPC 2.0 protocol
- Tool registration and invocation
- Request/response handling

### Job Store (`internal/jobs/store.go`)
- In-memory + PostgreSQL persistence
- Job state management
- Pub/sub for SSE streaming

### Queue Client (`internal/queue/rabbitmq.go`)
- RabbitMQ message production
- Route-based message creation
- Error handling

## Next Steps

- [Sidecar Component](sidecar.md) - Message routing
- [Runtime Component](runtime.md) - Actor processing
- [Deployment Guide](../guides/deployment.md)
