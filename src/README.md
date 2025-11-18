# Source Components

All framework components and build scripts.

## Components

### asya-gateway (Go)
MCP gateway with JSON-RPC 2.0, PostgreSQL envelope storage, and SSE streaming.

**Purpose**: API integration, envelope tracking, SSE streaming for long-running envelopes

[Read more →](asya-gateway/README.md)

### asya-sidecar (Go)
Actor sidecar for envelope routing between queues and runtimes.

**Purpose**: Consume from queues, route envelopes, forward to runtime via Unix socket

[Read more →](asya-sidecar/README.md)

### asya-runtime (Python)
Lightweight Unix socket server for actor-sidecar communication.

**Purpose**: Load user functions, handle OOM recovery, execute actor logic

[Read more →](asya-runtime/README.md)

### asya-crew (Python)
System actors with reserved roles for pipelines.

**Actors**:
- `happy-end`: Persist successful results to S3, report status to gateway
- `error-end`: Retry with exponential backoff, DLQ handling, error reporting

[Read more →](asya-crew/README.md)

## Building Images

Build all framework images:

```bash
./src/build-images.sh
```

**Options**:
```bash
# Custom tag
./src/build-images.sh --tag v1.0.0

# Build for ARM (M1/M2 Mac)
./src/build-images.sh --platform linux/arm64

# Build and push to registry
./src/build-images.sh --push --registry docker.io/myuser --tag v1.0.0
```

**Available parameters**: `--tag`, `--registry`, `--platform`, `--push`

**Makefile target**: `make build-images` (recommended)

## Development

### Building Individual Components

**Gateway**:
```bash
cd asya-gateway
go build -o bin/gateway ./cmd/gateway
docker build -t asya-gateway:dev .
```

**Sidecar**:
```bash
cd asya-sidecar
make build
docker build -t asya-sidecar:dev .
```

**Runtime**:
```bash
cd asya-runtime
docker build -t asya-runtime:dev .
```

**Actors**:
```bash
cd asya-crew/happy-end
docker build -t asya-happy-end:dev .

cd asya-crew/error-end
docker build -t asya-error-end:dev .
```

### Testing

Run unit tests for all components:
```bash
make unit-tests
```

Run integration tests:
```bash
make integration-tests
```

## Architecture

```
┌─────────────────┐
│  asya-gateway   │ ◄── HTTP/MCP clients
└────────┬────────┘
         │
    ┌────▼─────────────────────────────┐
    │      RabbitMQ / SQS Queues       │
    └────┬─────────────────────────────┘
         │
    ┌────▼────────┐
    │ asya-sidecar│ ◄── Consume envelopes
    └────┬────────┘
         │ Unix socket
    ┌────▼─────────┐
    │ asya-runtime │ ◄── Execute user function
    └──────────────┘
         │
    ┌────▼──────────────────────┐
    │ Crew Actors               │
    │ • happy-end (success)     │
    │ • error-end (retry/error) │
    └───────────────────────────┘
```

## Next Steps

- [Deployment Guide](../docs/guides/deploy.md)
- [Testing Guide](../docs/guides/testing.md)
- [Development Guide](../docs/guides/development.md)
