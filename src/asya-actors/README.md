# Asya Actors

Common terminal actors used in most generic Asya pipelines. These actors handle the final states of job execution: successful completion and error handling.

## Overview

Terminal actors are special actors that represent the end of a processing pipeline. Instead of forwarding messages to the next step in the route, they report the final job status back to the gateway and terminate the pipeline.

The two standard terminal actors provided here are:

1. **happy-end**: Handles successful job completions
2. **error-end**: Handles failed jobs with retry logic and error persistence

## Actor Descriptions

### happy-end

**Purpose**: Reports successful job completion to the gateway.

**Behavior**:
- Receives messages that have successfully completed all pipeline steps
- Extracts the final result from the payload
- Reports `Succeeded` status to the gateway via `POST /jobs/{job_id}/final`
- Returns `None` to signal pipeline termination (no further routing)

**Configuration**:
- `ASYA_GATEWAY_URL` (required): Gateway base URL for status reporting
- `ASYA_HANDLER`: Set to `happy_end_handler.happy_end_handler`

**Message Format**:
```json
{
  "job_id": "uuid-string",
  "payload": {
    "result": { ... }
  }
}
```

**Gateway Request**:
```json
POST /jobs/{job_id}/final
{
  "status": "Succeeded",
  "result": { ... },
  "error": null
}
```

### error-end

**Purpose**: Handles failed jobs with retry logic and error persistence.

**Behavior**:
- Receives messages that failed during pipeline execution
- Implements exponential backoff retry logic
- Stores error details in MinIO/S3 for debugging
- Reports `Failed` status to gateway after max retries exhausted
- Returns retry message (re-queued to error-end) or `None` (terminal)

**Configuration**:
- `ASYA_GATEWAY_URL` (required): Gateway base URL for status reporting
- `ASYA_ERROR_MAX_RETRIES` (default: 3): Maximum retry attempts before marking as failed
- `ASYA_ERROR_RETRY_DELAY_BASE` (default: 5): Base delay in seconds for exponential backoff
- `ASYA_HANDLER`: Set to `error_end_handler.error_end_handler`

**MinIO/S3 Configuration** (optional):
- `MINIO_ENABLED` (default: true): Enable MinIO error storage
- `MINIO_ENDPOINT`: MinIO endpoint (e.g., `minio:9000`)
- `MINIO_ACCESS_KEY`: MinIO access key
- `MINIO_SECRET_KEY`: MinIO secret key
- `MINIO_BUCKET` (default: asya-errors): Bucket for error storage
- `MINIO_SECURE` (default: false): Use HTTPS for MinIO connection

**Message Format**:
```json
{
  "job_id": "uuid-string",
  "error": "error message",
  "retry_count": 0
}
```

**Retry Logic**:
- Retry count < ASYA_ERROR_MAX_RETRIES: Returns retry message with incremented count
- Retry count >= ASYA_ERROR_MAX_RETRIES: Reports failure to gateway, returns None

**MinIO Storage**:
- Key structure: `errors/{job_id}/error_{timestamp}.json`
- Stores full error context including retry history

**Gateway Request** (after max retries):
```json
POST /jobs/{job_id}/final
{
  "status": "Failed",
  "result": null,
  "error": "error message"
}
```

## Deployment

These actors are designed to be deployed as standalone Kubernetes deployments with the Asya sidecar pattern.

**Example Kubernetes Deployment**:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: happy-end-actor
spec:
  replicas: 2
  template:
    spec:
      volumes:
        - name: sockets
          emptyDir: {}
      containers:
        # Runtime container
        - name: runtime
          image: your-registry/asya-runtime:latest
          env:
            - name: ASYA_HANDLER
              value: "happy_end_handler.happy_end_handler"
            - name: ASYA_SOCKET_PATH
              value: "/tmp/sockets/app.sock"
            - name: ASYA_GATEWAY_URL
              value: "http://asya-gateway:8080"
          volumeMounts:
            - name: sockets
              mountPath: /tmp/sockets

        # Sidecar container
        - name: sidecar
          image: your-registry/asya-sidecar:latest
          env:
            - name: ASYA_RABBITMQ_URL
              value: "amqp://guest:guest@rabbitmq:5672/"
            - name: ASYA_QUEUE_NAME
              value: "happy-end"
            - name: ASYA_SOCKET_PATH
              value: "/tmp/sockets/app.sock"
          volumeMounts:
            - name: sockets
              mountPath: /tmp/sockets
```

**Using with Docker Compose**:

See `tests/integration/gateway-vs-actors/docker-compose.yml` for complete examples of deploying these actors with the full Asya stack.

## Testing

Unit tests are provided for both actors in their respective `tests/` directories.

**Run tests**:
```bash
# Test all actors
make test

# Test individual actors
cd happy-end && uv run pytest tests/
cd error-end && uv run pytest tests/
```

**Test coverage includes**:
- Successful job completion (happy-end)
- Gateway HTTP error handling
- Missing configuration handling
- Retry logic and backoff (error-end)
- MinIO integration and error storage (error-end)
- Max retries exhaustion (error-end)

## Integration with Gateway

Both actors use the gateway's `POST /jobs/{job_id}/final` endpoint to report terminal status.

**Gateway Endpoint**:
```
POST /jobs/{job_id}/final
Content-Type: application/json

{
  "status": "Succeeded" | "Failed",
  "result": <any> | null,
  "error": string | null
}
```

**Gateway Behavior**:
- Updates job status in database
- Closes SSE streams for the job
- Broadcasts final status to any active listeners
- Marks job as complete (no further updates accepted)

## Usage in Routes

Configure your gateway routes to use these terminal actors:

**Example route configuration** (`gateway-routes.yaml`):
```yaml
tools:
  - name: process_data
    description: Process data through pipeline
    parameters:
      input: {type: string, required: true}
    route:
      - parser-queue
      - processor-queue
      - validator-queue
      - happy-end      # Success path
    error_route:
      - error-end       # Error path
```

**Default Terminal Queues**:
By convention, the Asya framework uses these queue names:
- `happy-end`: For successful completions
- `error-end`: For failures and errors

All sidecars are configured to route to these terminal queues when:
- Pipeline completes successfully → `happy-end`
- Error or timeout occurs → `error-end`

## Development

When adding new terminal actors or modifying existing ones:

1. **Handler Contract**: Must accept `msg: dict` and return `None` or retry message
2. **Testing**: Add comprehensive unit tests covering all code paths
3. **Documentation**: Update this README with configuration and behavior
4. **Dependencies**: Update `requirements.txt` if adding dependencies
5. **Integration Tests**: Verify with full stack in `tests/integration/gateway-vs-actors/`

## See Also

- `src/asya-runtime/`: Base runtime framework for actors
- `src/asya-sidecar/`: Sidecar that manages message routing
- `src/asya-gateway/`: Gateway that orchestrates jobs
- `tests/integration/gateway-vs-actors/`: Full integration test suite
