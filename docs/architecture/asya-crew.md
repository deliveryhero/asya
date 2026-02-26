# Asya Crew

System actors with reserved roles for framework-level tasks.

## Overview

Crew actors are **end actors** that run in special sidecar mode (`ASYA_IS_END_ACTOR=true`). They:

- Accept messages with ANY route state (no route validation)
- Do NOT route responses to any queue (terminal processing)
- Persist results to S3/MinIO (optional)
- Sidecar reports final task status to gateway (not the runtime)

## Current Crew Actors

### x-sink

**Responsibilities**:

- Persist successfully completed messages to S3/MinIO (optional)
- Sidecar reports task success to gateway with result payload

**Queue**: `asya-{namespace}-x-sink` (automatically routed by sidecar when pipeline completes)

**Handler**: `asya_crew.checkpointer.handler`

**Environment Variables**:
```yaml
# Required (auto-injected by operator)
- name: ASYA_HANDLER
  value: asya_crew.checkpointer.handler

# Checkpoint persistence mount point
- name: ASYA_PERSISTENCE_MOUNT
  value: /state/checkpoints
```

**S3 Key Structure**:
```
{prefix}{timestamp}/{last_actor}/{message_id}.json

Example:
sink-asya/2025-11-18T14:30:45.123456Z/text-processor/abc-123.json
```

**Flow**:
1. Sidecar receives message from `asya-{namespace}-x-sink` queue
2. Sidecar forwards message to runtime via Unix socket
3. Runtime persists complete message to S3 (if configured)
4. Runtime returns empty dict `{}`
5. Sidecar reports final task status `succeeded` to gateway with result payload
6. Sidecar acks message (does NOT route anywhere)

### x-sump

**Responsibilities**:

- Persist failed messages to S3/MinIO (optional)
- Sidecar reports task failure to gateway with error details and actor info

**Queue**: `asya-{namespace}-x-sump` (automatically routed by sidecar when runtime/sidecar errors occur)

**Handler**: `asya_crew.checkpointer.handler`

**Environment Variables**:
```yaml
# Required (auto-injected by operator)
- name: ASYA_HANDLER
  value: asya_crew.checkpointer.handler

# Checkpoint persistence mount point
- name: ASYA_PERSISTENCE_MOUNT
  value: /state/checkpoints
```

**S3 Key Structure**:
```
{prefix}{timestamp}/{last_actor}/{message_id}.json

Example:
error-asya/2025-11-18T14:30:45.123456Z/failing-actor/abc-123.json
```

**Error Message Structure**:
Messages routed to `x-sump` contain error information in the payload:
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
1. Sidecar receives error message from `asya-{namespace}-x-sump` queue
2. Sidecar forwards message to runtime via Unix socket
3. Runtime persists complete message (with error details) to S3 (if configured)
4. Runtime returns empty dict `{}`
5. Sidecar extracts error info from message payload
6. Sidecar reports final task status `failed` to gateway with error details and actor information
7. Sidecar acks message (does NOT route anywhere)

## Deployment

Crew actors deployed via Helm chart that creates AsyncActor CRDs:

```bash
helm install asya-crew deploy/helm-charts/asya-crew/ \
  --namespace asya-e2e
```

**Chart structure**:

- Creates two AsyncActor resources: `x-sink` and `x-sump`
- Operator handles sidecar injection and `ASYA_IS_END_ACTOR=true` flag

**Default configuration** (from `values.yaml`):
```yaml
x-sink:
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
          image: ghcr.io/deliveryhero/asya-crew:latest
          env:
          - name: ASYA_HANDLER
            value: asya_crew.checkpointer.handler
          # Optional S3 configuration (uncomment to enable)
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 128Mi

x-sump:
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
          image: ghcr.io/deliveryhero/asya-crew:latest
          env:
          - name: ASYA_HANDLER
            value: asya_crew.checkpointer.handler
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
x-sink:
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: asya_crew.checkpointer.handler
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints

x-sump:
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_HANDLER
            value: asya_crew.checkpointer.handler
          - name: ASYA_PERSISTENCE_MOUNT
            value: /state/checkpoints
```

Deploy with custom values:
```bash
helm install asya-crew deploy/helm-charts/asya-crew/ \
  --namespace asya-e2e \
  --values custom-values.yaml
```

## Implementation Details

### S3 Persistence

**Bucket auto-creation**: Handlers check if bucket exists and create it if missing (for MinIO/S3).

**Key structure breakdown**:

- `{prefix}`: Configurable prefix (default: `sink-asya/` or `error-asya/`)
- `{timestamp}`: ISO 8601 UTC timestamp (`2025-11-18T14:30:45.123456Z`)
- `{last_actor}`: Last non-end actor from route (extracted from `route.actors[current]`)
- `{message_id}`: Message ID

**Example key generation**:
```python
prefix = "sink-asya/"
timestamp = "2025-11-18T14:30:45.123456Z"
last_actor = "text-processor"  # from route.actors[1] if current=1
message_id = "abc-123"

key = f"{prefix}{timestamp}/{last_actor}/{message_id}.json"
# Result: sink-asya/2025-11-18T14:30:45.123456Z/text-processor/abc-123.json
```

**Persisted content**: Complete message (including id, route, headers, payload) as formatted JSON.

**Error handling**: S3 upload failures are logged but do NOT fail the handler. Handler returns empty dict `{}` regardless of S3 success/failure.

### Handler Return Value

End handlers MUST return empty dict `{}`:

- Sidecar ignores the response (end actor mode)
- Sidecar uses original message payload as result for gateway reporting
- Any non-empty response is ignored

### Sidecar Integration

When `ASYA_IS_END_ACTOR=true`, sidecar:
1. Accepts messages with any route state (no validation)
2. Sends message to runtime without route checking
3. Receives empty dict `{}` from runtime (ignored)
4. Extracts result/error from original message payload
5. Reports final task status to gateway:
   - `x-sink`: Task status `succeeded` with result payload
   - `x-sump`: Task status `failed` with error details, actor info, route
6. Does NOT route to any queue (terminal)
7. Acks message

## Future Crew Actors

**Fan-in**:

- Aggregate fan-out results
- Wait for all chunks to complete
- Merge results and continue pipeline
- Track parent-child relationships via `parent_id`

**Auto-retry** functionality by `x-sump`:

- Implement exponential backoff
- Classify errors as retriable vs permanent
- Track retry count in message headers
- Re-queue retriable messages with backoff delay
- Move to DLQ after max retries exceeded

**Custom monitoring**:

- Track SLA violations per actor
- Alert on error rates and patterns
- Generate pipeline execution reports
- Aggregate metrics across messages
