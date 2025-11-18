# Asya Crew

System actors with reserved roles for framework-level tasks.

## Overview

Crew actors are **end actors** that run in special sidecar mode (`ASYA_IS_END_ACTOR=true`). They:

- Run in envelope mode (`ASYA_HANDLER_MODE=envelope`)
- Disable envelope validation (`ASYA_ENABLE_VALIDATION=false`)
- Accept envelopes with ANY route state (no route validation)
- Do NOT route responses to any queue (terminal processing)
- Persist results to S3/MinIO (optional)
- Sidecar reports final status to gateway (not the runtime)

## Current Crew Actors

### happy-end

**Responsibilities**:

- Persist successfully completed envelopes to S3/MinIO (optional)
- Sidecar reports success to gateway with result payload

**Queue**: `asya-happy-end` (automatically routed by sidecar when pipeline completes)

**Handler**: `handlers.end_handlers.happy_end_handler`

**Environment Variables**:
```yaml
# Required (auto-injected by operator)
- name: ASYA_HANDLER_MODE
  value: envelope
- name: ASYA_ENABLE_VALIDATION
  value: "false"
- name: ASYA_HANDLER
  value: handlers.end_handlers.happy_end_handler

# Optional S3/MinIO persistence
- name: ASYA_S3_BUCKET
  value: asya-results
- name: ASYA_S3_ENDPOINT
  value: http://minio:9000  # Omit for AWS S3
- name: ASYA_S3_ACCESS_KEY
  value: minioadmin  # Optional for MinIO
- name: ASYA_S3_SECRET_KEY
  value: minioadmin  # Optional for MinIO
- name: ASYA_S3_RESULTS_PREFIX
  value: happy-asya/  # Default prefix
- name: AWS_REGION
  value: us-east-1  # For AWS S3 only
```

**S3 Key Structure**:
```
{prefix}{timestamp}/{last_actor}/{envelope_id}.json

Example:
happy-asya/2025-11-18T14:30:45.123456Z/text-processor/abc-123.json
```

**Flow**:
1. Sidecar receives envelope from `asya-happy-end` queue
2. Sidecar forwards envelope to runtime via Unix socket
3. Runtime persists complete envelope to S3 (if configured)
4. Runtime returns empty dict `{}`
5. Sidecar reports final status `succeeded` to gateway with result payload
6. Sidecar acks message (does NOT route anywhere)

### error-end

**Responsibilities**:

- Persist failed envelopes to S3/MinIO (optional)
- Sidecar reports failure to gateway with error details and actor info

**Queue**: `asya-error-end` (automatically routed by sidecar when runtime/sidecar errors occur)

**Handler**: `handlers.end_handlers.error_end_handler`

**Environment Variables**:
```yaml
# Required (auto-injected by operator)
- name: ASYA_HANDLER_MODE
  value: envelope
- name: ASYA_ENABLE_VALIDATION
  value: "false"
- name: ASYA_HANDLER
  value: handlers.end_handlers.error_end_handler

# Optional S3/MinIO persistence
- name: ASYA_S3_BUCKET
  value: asya-results
- name: ASYA_S3_ENDPOINT
  value: http://minio:9000  # Omit for AWS S3
- name: ASYA_S3_ACCESS_KEY
  value: minioadmin  # Optional for MinIO
- name: ASYA_S3_SECRET_KEY
  value: minioadmin  # Optional for MinIO
- name: ASYA_S3_ERRORS_PREFIX
  value: error-asya/  # Default prefix
- name: AWS_REGION
  value: us-east-1  # For AWS S3 only
```

**S3 Key Structure**:
```
{prefix}{timestamp}/{last_actor}/{envelope_id}.json

Example:
error-asya/2025-11-18T14:30:45.123456Z/failing-actor/abc-123.json
```

**Error Envelope Structure**:
Envelopes routed to `error-end` contain error information in the payload:
```json
{
  "id": "abc-123",
  "route": {
    "actors": ["preprocess", "infer", "postprocess"],
    "current": 1
  },
  "payload": {
    "error": "Runtime timeout exceeded",
    "details": {
      "message": "Processing timeout after 5m",
      "type": "TimeoutError",
      "traceback": "..."
    },
    "original_payload": {"input": "..."}
  }
}
```

**Flow**:
1. Sidecar receives error envelope from `asya-error-end` queue
2. Sidecar forwards envelope to runtime via Unix socket
3. Runtime persists complete envelope (with error details) to S3 (if configured)
4. Runtime returns empty dict `{}`
5. Sidecar extracts error info from envelope payload
6. Sidecar reports final status `failed` to gateway with error details and actor information
7. Sidecar acks message (does NOT route anywhere)

## Deployment

Crew actors deployed via Helm chart that creates AsyncActor CRDs:

```bash
helm install asya-crew deploy/helm-charts/asya-crew/ \
  --namespace asya-e2e
```

**Chart structure**:

- Creates two AsyncActor resources: `happy-end` and `error-end`
- Helm templates inject required environment variables (`ASYA_HANDLER_MODE=envelope`, `ASYA_ENABLE_VALIDATION=false`)
- Operator handles sidecar injection and `ASYA_IS_END_ACTOR=true` flag

**Default configuration** (from `values.yaml`):
```yaml
happy-end:
  enabled: true
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 10
    queueLength: 5
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: asya-crew:latest
          env:
          - name: ASYA_HANDLER
            value: handlers.end_handlers.happy_end_handler
          # Optional S3 configuration (uncomment to enable)
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 128Mi

error-end:
  enabled: true
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 10
    queueLength: 5
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: asya-crew:latest
          env:
          - name: ASYA_HANDLER
            value: handlers.end_handlers.error_end_handler
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 128Mi
```

**Namespace**: Deployed to release namespace (e.g., `asya-e2e`, `default`)

**Custom values example**:
```yaml
# custom-values.yaml
happy-end:
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: handlers.end_handlers.happy_end_handler
          - name: ASYA_S3_BUCKET
            value: my-results-bucket
          - name: ASYA_S3_ENDPOINT
            value: http://minio.storage:9000
          - name: ASYA_S3_ACCESS_KEY
            value: minioadmin
          - name: ASYA_S3_SECRET_KEY
            value: minioadmin

error-end:
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: handlers.end_handlers.error_end_handler
          - name: ASYA_S3_BUCKET
            value: my-results-bucket
          - name: ASYA_S3_ENDPOINT
            value: http://minio.storage:9000
```

Deploy with custom values:
```bash
helm install asya-crew deploy/helm-charts/asya-crew/ \
  --namespace asya-e2e \
  --values custom-values.yaml
```

## Implementation Details

### Handler Requirements

End handlers MUST satisfy these requirements (enforced at import time):

1. **Envelope mode required**:
   ```python
   if ASYA_HANDLER_MODE != "envelope":
       raise RuntimeError("End handlers must run in envelope mode")
   ```

2. **Validation disabled**:
   ```python
   if ASYA_ENABLE_VALIDATION:
       raise RuntimeError("End handlers must run with validation disabled")
   ```

These are automatically configured by Helm templates and operator injection.

### S3 Persistence

**Bucket auto-creation**: Handlers check if bucket exists and create it if missing (for MinIO/S3).

**Key structure breakdown**:

- `{prefix}`: Configurable prefix (default: `happy-asya/` or `error-asya/`)
- `{timestamp}`: ISO 8601 UTC timestamp (`2025-11-18T14:30:45.123456Z`)
- `{last_actor}`: Last non-end actor from route (extracted from `route.actors[current]`)
- `{envelope_id}`: Envelope ID

**Example key generation**:
```python
prefix = "happy-asya/"
timestamp = "2025-11-18T14:30:45.123456Z"
last_actor = "text-processor"  # from route.actors[1] if current=1
envelope_id = "abc-123"

key = f"{prefix}{timestamp}/{last_actor}/{envelope_id}.json"
# Result: happy-asya/2025-11-18T14:30:45.123456Z/text-processor/abc-123.json
```

**Persisted content**: Complete envelope (including id, route, headers, payload) as formatted JSON.

**Error handling**: S3 upload failures are logged but do NOT fail the handler. Handler returns empty dict `{}` regardless of S3 success/failure.

### Handler Return Value

End handlers MUST return empty dict `{}`:

- Sidecar ignores the response (end actor mode)
- Sidecar uses original envelope payload as result for gateway reporting
- Any non-empty response is ignored

### Sidecar Integration

When `ASYA_IS_END_ACTOR=true`, sidecar:
1. Accepts envelopes with any route state (no validation)
2. Sends envelope to runtime without route checking
3. Receives empty dict `{}` from runtime (ignored)
4. Extracts result/error from original envelope payload
5. Reports final status to gateway:
   - `happy-end`: Status `succeeded` with result payload
   - `error-end`: Status `failed` with error details, actor info, route
6. Does NOT route to any queue (terminal)
7. Acks message

## Future Crew Actors

**Stateful fan-in**:

- Aggregate fan-out results
- Wait for all chunks to complete
- Merge results and continue pipeline
- Track parent-child relationships via `parent_id`

**Auto-retry** functionality by `error-end`:

- Implement exponential backoff
- Classify errors as retriable vs permanent
- Track retry count in envelope headers
- Re-queue retriable envelopes with backoff delay
- Move to DLQ after max retries exceeded

**Custom monitoring**:

- Track SLA violations per actor
- Alert on error rates and patterns
- Generate pipeline execution reports
- Aggregate metrics across envelopes
