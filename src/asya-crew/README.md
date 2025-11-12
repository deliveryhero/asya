# Crew Actors

Crew actors with pre-defined roles for Asya🎭 pipelines: `happy-end` (successful completion) and `error-end` (error handling).

## Overview

End actors finish the processing pipeline by persisting results to S3 and returning metadata to the sidecar. The sidecar reports final status to the gateway.

## happy-end

Persists successful results to S3 and returns metadata for sidecar to report to gateway.

### Behavior

1. Receives messages with successful results
2. Persists results to S3/MinIO (if configured)
3. Returns result and S3 metadata to sidecar
4. Sidecar reports final status to gateway

### Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `ASYA_HANDLER` | ✅ | Set to `handlers.end_handlers.happy_end_handler` |
| `ASYA_S3_BUCKET` | ❌ | S3/MinIO bucket for storing results |
| `ASYA_S3_ENDPOINT` | ❌ | MinIO endpoint (omit for AWS S3) |
| `ASYA_S3_ACCESS_KEY` | ❌ | S3/MinIO credentials |
| `ASYA_S3_SECRET_KEY` | ❌ | S3/MinIO credentials |

### Message Format

```json
{
  "job_id": "uuid",
  "payload": {"result": {...}}
}
```

## error-end

Persists errors to S3 and returns error metadata for sidecar to report to gateway.

### Behavior

1. Receives error messages
2. Persists errors to S3/MinIO for debugging (if configured)
3. Returns error and S3 metadata to sidecar
4. Sidecar reports final failure status to gateway

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_HANDLER` | - | Set to `handlers.end_handlers.error_end_handler` |
| `ASYA_S3_BUCKET` | - | S3/MinIO bucket for errors |
| `ASYA_S3_ENDPOINT` | - | MinIO endpoint (omit for AWS) |
| `ASYA_S3_ACCESS_KEY` | - | S3/MinIO credentials |
| `ASYA_S3_SECRET_KEY` | - | S3/MinIO credentials |

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

- **Results** (happy-end): `{prefix}{timestamp}/{last_actor}/{id}.json`
- **Errors** (error-end): `{prefix}{timestamp}/{last_actor}/{id}.json`

Example: `happy-asya/2025-11-11T10:30:45.123456Z/text-analyzer/abc-123.json`

## Deployment

Deploy using AsyncActor CRD (operator handles sidecar injection):

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: happy-end
spec:
  transport: rabbitmq
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: asya-runtime:latest
          env:
          - name: ASYA_HANDLER
            value: "handlers.end_handlers.happy_end_handler"
          - name: ASYA_S3_BUCKET
            value: "asya-results"
```

See [operator README](../../operator/README.md) for operator deployment.

## Testing

```bash
# All actors
make test

# Individual
cd happy-end && uv run pytest tests/
cd error-end && uv run pytest tests/
```

## Architecture

End actors follow strict separation of concerns:

- **Runtime (Python)**: Persists to S3, returns metadata
- **Sidecar (Go)**: Reports final status to gateway via `POST /envelopes/{id}/final`

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
- When route completes successfully → `happy-end` queue
- When errors occur → `error-end` queue

**Never configure `happy-end` or `error-end` in routes** - the sidecar automatically routes to these end queues based on processing results.

## See Also

- [Sidecar README](../asya-sidecar/README.md) - Actor sidecar (manages routing logic)
- [Runtime README](../asya-runtime/README.md) - Actor runtime (injected into user's container)
- [Gateway README](../asya-gateway/README.md) - Optional MCP-compliant gateway to use actors
