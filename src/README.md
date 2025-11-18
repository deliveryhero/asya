# Source Components

All framework components and build scripts.

## Components

### asya-gateway (Go)
MCP gateway with JSON-RPC 2.0, PostgreSQL envelope storage, and SSE streaming.

**Purpose**: API integration, envelope tracking, SSE streaming for long-running envelopes

**See**: [Architecture docs](../docs/architecture/asya-gateway.md) | [Component README](asya-gateway/README.md)

### asya-sidecar (Go)
Actor sidecar for envelope routing between queues and runtimes.

**Purpose**: Consume from queues, route envelopes, forward to runtime via Unix socket

**See**: [Architecture docs](../docs/architecture/asya-sidecar.md) | [Component README](asya-sidecar/README.md)

### asya-runtime (Python)
Lightweight Unix socket server for actor-sidecar communication.

**Purpose**: Load user functions, handle OOM recovery, execute actor logic

**See**: [Architecture docs](../docs/architecture/asya-runtime.md) | [Component README](asya-runtime/README.md)

### asya-crew (Python)
System actors with reserved roles for pipelines.

**Actors**:
- `happy-end`: Persist successful results to S3, report status to gateway
- `error-end`: Retry with exponential backoff, DLQ handling, error reporting

**See**: [Architecture docs](../docs/architecture/asya-crew.md) | [Component README](asya-crew/README.md)

## Building Images

Build all framework images:

```bash
make build-images
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for detailed build instructions.

## Development

See [CONTRIBUTING.md](../CONTRIBUTING.md) for complete development guide including:
- Building individual components
- Running tests (unit, component, integration, E2E)
- Linting and code coverage

## Architecture

See [docs/architecture/README.md](../docs/architecture/README.md) for complete architecture documentation with system diagrams, component details, and message flow.
