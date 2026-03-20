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
  scaling:
    enabled: true
    minReplicaCount: 1
    maxReplicaCount: 10
    queueLength: 5
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 200m
      memory: 128Mi

x-sump:
  enabled: true
  scaling:
    enabled: true
    minReplicaCount: 1
    maxReplicaCount: 10
    queueLength: 5
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
  env:
    ASYA_PERSISTENCE_MOUNT: /state/checkpoints

x-sump:
  env:
    ASYA_PERSISTENCE_MOUNT: /state/checkpoints
```

Deploy with custom values:
```bash
helm install asya-crew deploy/helm-charts/asya-crew/ \
  --namespace asya-e2e \
  --values custom-values.yaml
```

## Implementation Details

### Checkpointer

The checkpointer (`src/asya-crew/asya_crew/checkpointer.py`) persists complete messages (metadata + payload) as JSON files via the state proxy filesystem abstraction. The storage backend is pluggable — S3, GCS, or any backend supported by the state proxy connector configured in the AsyncActor CRD.

**Storage Backend**:

The checkpointer writes through the state proxy mount, not directly to cloud storage. The mount path is configured via `ASYA_PERSISTENCE_MOUNT`. The state proxy connector sidecar transparently syncs writes to the configured backend.

This keeps the checkpointer backend-agnostic: the same Python code works for S3, GCS, NATS, Redis, or any future connector that implements the state proxy interface.

**Key Pattern**:

Files are stored at `{mount}/{prefix}/{id}.json`:

| `status.phase`   | `prefix`     | Example key               |
|------------------|-------------|---------------------------|
| `succeeded`      | `succeeded` | `succeeded/msg-123.json`  |
| `failed`         | `failed`    | `failed/msg-456.json`     |
| (mid-pipeline)   | `checkpoint`| `checkpoint/msg-789.json` |

The flat `{prefix}/{id}.json` pattern is chosen because the gateway already knows the task ID (= message ID) and the final status. It can reconstruct the object key without querying any index — no DB column or header needed for lookup.

**Security**: Message IDs are sanitized with `os.path.basename()` before use in paths to prevent path traversal attacks (e.g., a crafted ID like `../../etc/passwd`).

The actor name and timestamp are preserved inside the JSON body (`route.prev`, `status.phase`) for debugging and analytics.

**JSON Schema**:

```json
{
  "id": "<message-id>",
  "parent_id": "<parent-id>",   // omitted if empty (fanout child only)
  "route": {
    "prev": ["actor-a", "actor-b"],
    "curr": "x-sink"
  },
  "status": { "phase": "succeeded" },  // omitted if no phase
  "payload": { ... }
}
```

**Persisted content**: Complete message (including id, route, payload, status) as formatted JSON.

**Error handling**: Storage write failures are logged but do NOT fail the handler. The handler continues regardless of persistence success/failure.

**Graceful skip**: If `ASYA_PERSISTENCE_MOUNT` is not set, the checkpointer logs a debug message and returns immediately. This allows crew actors to run in environments without persistence configured (e.g., lightweight test setups).

**State Proxy Configuration**:

Persistence is wired through an `EnvironmentConfig` flavor that adds a state proxy sidecar to the crew actor pods. The flavor configures:

- `spec.stateProxy.connector.image` — backend-specific connector image (e.g., `asya-state-proxy-s3-buffered-lww`, `asya-state-proxy-gcs-buffered-lww`)
- `spec.stateProxy.mount.path` — filesystem path visible to the checkpointer
- Backend-specific env vars (bucket, endpoint, credentials) passed to the connector

Example crew chart snippet for the GCS profile:

```yaml
crew:
  persistence:
    enabled: true
    backend: gcs
    config:
      bucket: asya-results
      project: my-gcp-project
    connector:
      image: ghcr.io/deliveryhero/asya-state-proxy-gcs-buffered-lww:latest
  x-sink:
    env:
      ASYA_PERSISTENCE_MOUNT: "/state/checkpoints/results"
```

**Future: Date-Partitioned Keys**:

Data scientists can query historical checkpointed messages using DuckDB over the object store. The current flat `{prefix}/{id}.json` structure is scannable, but date-partitioned keys would enable more efficient glob queries.

Proposed future key pattern:

```
{prefix}/{YYYY-MM-DD}/{id}.json
```

Example:

```
succeeded/2026-03-06/msg-123.json
failed/2026-03-06/msg-456.json
```

This enables DuckDB queries scoped by date:

```sql
SELECT *
FROM read_json_auto('s3://asya-results/succeeded/2026-03-06/*.json')
WHERE json_extract_string(payload, '$.model') = 'sdxl'
```

With date-partitioned keys, the gateway can reconstruct the key by deriving the date from `tasks.updated_at::date`: `{status}/{tasks.updated_at::date}/{id}.json`.

⚠️ Not yet implemented. Date partitioning is planned as a follow-up when DuckDB OLAP use cases are confirmed.

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
