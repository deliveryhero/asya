# Asya Crew

System actors with reserved roles for framework-level tasks.

## Overview

Crew actors are **end actors** that run in special sidecar mode (`ASYA_IS_END_ACTOR=true`). They:

- Accept messages with ANY route state (no route validation)
- Do NOT route responses to any queue (terminal processing)
- Persist results to object storage via state proxy (optional)
- Sidecar reports final task status to gateway (not the runtime)

## Current Crew Actors

### x-sink

**Responsibilities**:

- First layer of two-layer termination: receives messages when pipeline completes
- Persists results to object storage via state proxy (optional, when `ASYA_PERSISTENCE_MOUNT` is set)
- Suppresses fan-in partials (messages with `x-asya-fan-in` header are silently consumed)
- Routes to configurable hooks (e.g. checkpoint-s3, notify-slack) via `ASYA_SINK_HOOKS`
- Sidecar reports task success to gateway with result payload

**Queue**: `asya-{namespace}-x-sink` (automatically routed by sidecar when pipeline completes)

**Handler**: `asya_crew.sink.sink_handler` (generator, uses ABI yield protocol)

**Environment Variables**:
```yaml
# Required (auto-injected by operator)
- name: ASYA_HANDLER
  value: asya_crew.sink.sink_handler

# Checkpoint persistence mount point (optional)
- name: ASYA_PERSISTENCE_MOUNT
  value: /state/checkpoints

# Hook actors to route to after checkpointing (optional, comma-separated)
- name: ASYA_SINK_HOOKS
  value: "checkpoint-s3,notify-slack"
```

**Storage Key Structure**:
```
{prefix}/{timestamp}/{last_actor}/{message_id}.json

Example:
succeeded/2025-11-18T14:30:45.123456Z/text-processor/abc-123.json
```

**Flow**:
1. Sidecar receives message from `asya-{namespace}-x-sink` queue
2. Sidecar forwards message to runtime via Unix socket
3. Generator handler reads envelope metadata via ABI (`GET .id`, `GET .headers`, etc.)
4. Fan-in partials (`x-asya-fan-in` header): handler returns without yielding — silently consumed
5. Normal messages: handler persists to storage (if configured), then `yield payload`
6. Sidecar reports final task status `succeeded` to gateway (skipped for fan-in partials and fan-out children)
7. Sidecar acks message (does NOT route anywhere)

### x-sump

**Responsibilities**:

- Second layer of two-layer termination: receives messages after hooks have been processed
- Persists failed messages to object storage via state proxy (optional)
- Logs terminal failures at ERROR level with full message summary
- Sidecar reports task failure to gateway with error details and actor info

**Queue**: `asya-{namespace}-x-sump` (automatically routed by sidecar when runtime/sidecar errors occur)

**Handler**: `asya_crew.sump.sump_handler` (generator, uses ABI yield protocol)

**Environment Variables**:
```yaml
# Required (auto-injected by operator)
- name: ASYA_HANDLER
  value: asya_crew.sump.sump_handler

# Checkpoint persistence mount point (optional)
- name: ASYA_PERSISTENCE_MOUNT
  value: /state/checkpoints
```

**Storage Key Structure**:
```
{prefix}/{timestamp}/{last_actor}/{message_id}.json

Example:
failed/2025-11-18T14:30:45.123456Z/failing-actor/abc-123.json
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
3. Generator handler reads metadata via ABI, logs failure details
4. Handler persists message to storage (if configured), then `yield payload`
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
    minReplicaCount: 1
    maxReplicaCount: 10
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
            value: asya_crew.sink.sink_handler  # or sump_handler for x-sump
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
    minReplicaCount: 1
    maxReplicaCount: 10
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
            value: asya_crew.sink.sink_handler  # or sump_handler for x-sump
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
            value: asya_crew.sink.sink_handler  # or sump_handler for x-sump
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
            value: asya_crew.sink.sink_handler  # or sump_handler for x-sump
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

### Storage Persistence

Crew actors persist messages to object storage via the state proxy sidecar. The storage backend (S3, GCS, MinIO) is configured through the state proxy connector in the AsyncActor CRD.

**Key structure breakdown**:

- `{prefix}`: Determined by status phase (`succeeded/`, `failed/`, or `checkpoint/`)
- `{timestamp}`: ISO 8601 UTC timestamp (`2025-11-18T14:30:45.123456Z`)
- `{last_actor}`: Last processed actor from `route.prev[-1]`
- `{message_id}`: Message ID (or `x-asya-origin-id` header for fan-in merged results)

**Example key generation**:
```python
prefix = "succeeded"
timestamp = "2025-11-18T14:30:45.123456Z"
last_actor = "text-processor"
message_id = "abc-123"

key = f"{prefix}/{timestamp}/{last_actor}/{message_id}.json"
# Result: succeeded/2025-11-18T14:30:45.123456Z/text-processor/abc-123.json
```

**Persisted content**: Complete message (including id, route, payload, status) as formatted JSON.

**Error handling**: Storage write failures are logged but do NOT fail the handler. The handler continues regardless of persistence success/failure.

### Handler Return Value

The sink and sump handlers are **generators** that use the ABI yield protocol. They `yield payload` at the end to emit a downstream frame. The sidecar captures the first frame for gateway reporting but does not route it anywhere (terminal processing).

| Handler behavior | Sidecar response |
|-----------------|-----------------|
| `yield payload` (normal message) | Captures payload, reports to gateway if terminal phase |
| `return` without yielding (fan-in partial) | Uses original envelope payload, skips gateway report |

**Gateway reporting** is controlled by `shouldReportFinalToGateway` in the sidecar, which skips reporting when:
- `x-asya-fan-in` header is present (fan-in accumulating slice)
- `parent_id` is set (fan-out child)
- Status phase is not `succeeded` or `failed`

### Sidecar Integration

When `ASYA_IS_END_ACTOR=true`, sidecar uses `processEndActorEnvelope`:
1. Accepts messages with any route state (no validation)
2. Sends message to runtime without route checking
3. Captures the first downstream frame from the generator (if any)
4. Falls back to original envelope payload if runtime returned nothing
5. Checks `shouldReportFinalToGateway` — reports only for terminal, non-fan-in/fan-out messages:
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
