# Crew Actors

Crew actors with pre-defined roles for 🎭 pipelines: `x-sink` (successful completion) and `x-sump` (error handling).

## Overview

End actors finish the processing pipeline by persisting results to S3 and returning metadata to the sidecar. The sidecar reports final status to the gateway.

## x-sink

Persists successful results to S3 and returns metadata for sidecar to report to gateway.

### Behavior

1. Receives messages with successful results
2. Persists results to S3/MinIO (if configured)
3. Returns result and S3 metadata to sidecar
4. Sidecar reports final status to gateway

### Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `ASYA_HANDLER` | ✅ | Set to `asya_crew.checkpointer.handler` |
| `ASYA_PERSISTENCE_MOUNT` | ✅ | Directory path for checkpoint persistence |

### Message Format

```json
{
  "job_id": "uuid",
  "payload": {"result": {...}}
}
```

## x-sump

Persists errors to S3 and returns error metadata for sidecar to report to gateway.

### Behavior

1. Receives error messages
2. Persists errors to S3/MinIO for debugging (if configured)
3. Returns error and S3 metadata to sidecar
4. Sidecar reports final failure status to gateway

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_HANDLER` | - | Set to `asya_crew.checkpointer.handler` |
| `ASYA_PERSISTENCE_MOUNT` | - | Directory path for checkpoint persistence |

### Message Format

```json
{
  "job_id": "uuid",
  "error": "error message",
  "retry_count": 0
}
```

### S3 Storage

Both handlers use the same key structure:

- **Results** (x-sink): `{prefix}{timestamp}/{last_actor}/{id}.json`
- **Errors** (x-sump): `{prefix}{timestamp}/{last_actor}/{id}.json`

Example: `sink-asya/2025-11-11T10:30:45.123456Z/text-analyzer/abc-123.json`

## Deployment

Deploy using AsyncActor CRD (operator handles sidecar injection):

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: x-sink
spec:
  transport: rabbitmq
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-actor:latest
          env:
          - name: ASYA_HANDLER
            value: "asya_crew.checkpointer.handler"
          - name: ASYA_PERSISTENCE_MOUNT
            value: "/state/checkpoints"
```

See [Crossplane README](../../deploy/helm-charts/asya-crossplane/README.md) for deployment.

## Testing

```bash
# All actors
make test

# Individual
cd x-sink && uv run pytest tests/
cd x-sump && uv run pytest tests/
```

## Architecture

End actors follow strict separation of concerns:

- **Runtime (Python)**: Persists to S3, returns metadata
- **Sidecar (Go)**: Reports final status to gateway via `POST /tasks/{id}/final`

The runtime never communicates directly with the gateway. All network communication is handled by the sidecar, maintaining clean architectural boundaries.

## Usage in Routes

Configure routes with processing actors only. End actors are automatically handled:

```yaml
# config/routes.yaml
tools:
  - name: process_data
    description: Process data
    parameters:
      input: {type: string, required: true}
    route: [parser, processor, validator]
```

**Automatic routing** (handled by sidecar):
- When route completes successfully → `x-sink` queue
- When errors occur → `x-sump` queue

**Never configure `x-sink` or `x-sump` in routes** - the sidecar automatically routes to these end queues based on processing results.

## See Also

- [Sidecar README](../asya-sidecar/README.md) - Actor sidecar (manages routing logic)
- [Runtime README](../asya-runtime/README.md) - Actor runtime (injected into user's container)
- [Gateway README](../asya-gateway/README.md) - Optional MCP-compliant gateway to use actors
