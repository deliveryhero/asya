# Crew

System actors with reserved roles for framework-level tasks.

## Overview

Crew actors are **terminal actors** that run with a dedicated sidecar role (`ASYA_ACTOR_ROLE`). The two roles are:

- `sink` — x-sink reports final status to gateway, then routes to configurable hooks
- `sump` — x-sump emits Prometheus metrics only; does NOT report to gateway

Both roles:

- Accept messages with ANY route state (no route validation)
- Persist results to object storage via state proxy (optional)

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

- Second layer (final terminal) of two-layer termination: receives messages from x-sink after hooks complete or fail
- Emits Prometheus metrics (hook success/failure counters)
- On error (`status.phase=failed`): logs the complete message JSON to stdout as last-resort persistence
- Does NOT report to gateway — metrics only
- ACKs and terminates; nothing routes below x-sump

**Queue**: `asya-{namespace}-x-sump` (reached via x-sink's `ASYA_ACTOR_SINK=x-sump` setting, not directly from regular actor sidecars)

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
Messages routed to `x-sump` contain error information in `status.error`, not in the payload:
```json
{
  "id": "abc-123",
  "route": {
    "prev": ["preprocess", "infer"],
    "curr": "x-sump"
  },
  "status": {
    "phase": "failed",
    "reason": "PolicyExhausted",
    "actor": "infer",
    "attempt": 3,
    "max_attempts": 3,
    "error": {
      "type": "TimeoutError",
      "mro": ["Exception"],
      "message": "Processing timeout after 5m",
      "traceback": "..."
    }
  },
  "payload": {"input": "..."}
}
```

**Flow**:
1. Sidecar receives message from `asya-{namespace}-x-sump` queue (routed from x-sink after hooks)
2. Sidecar forwards message to runtime via Unix socket
3. Generator handler reads metadata via ABI
4. Handler emits Prometheus metrics (hook_success / hook_failure counters)
5. On error (`status.phase=failed`): handler logs the complete message JSON to stdout
6. Handler returns without yielding (terminal)
7. Sidecar acks message (does NOT route anywhere, does NOT report to gateway)

## Deployment

Crew actors deployed via Helm chart that creates AsyncActor CRDs:

```bash
helm install asya-crew deploy/helm-charts/asya-crew/ \
  --namespace asya-e2e
```

**Chart structure**:

- Creates two AsyncActor resources: `x-sink` and `x-sump`
- Operator handles sidecar injection and sets `ASYA_ACTOR_ROLE` (`sink` for x-sink, `sump` for x-sump)

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

The sidecar behavior depends on `ASYA_ACTOR_ROLE`:

**`sink` role** (x-sink):
1. Accepts messages with any route state (no validation)
2. Sends message to runtime without route checking
3. Captures the first downstream frame from the generator (if any)
4. Falls back to original envelope payload if runtime returned nothing
5. Reports final task status to gateway (succeeded or failed) — skipped for fan-in partials and fan-out children
6. Routes to configured hooks via `ASYA_SINK_HOOKS`
7. Acks message

**`sump` role** (x-sump):
1. Accepts messages with any route state (no validation)
2. Sends message to runtime without route checking
3. Runtime emits Prometheus metrics and logs errors
4. Does NOT report to gateway
5. Does NOT route to any queue (terminal)
6. Acks message

## Fan-In Aggregator

**Handler**: `asya_crew.fanin.split_key.aggregator` (generator, uses ABI yield protocol)

**Source**: `src/asya-crew/asya_crew/fanin/split_key.py`

The fan-in aggregator collects N+1 messages from a fan-out operation and emits a single merged envelope. It uses the **S3 split-key pattern** via the state proxy sidecar: each slice writes its result to its own file under `/state/checkpoints/fanin/{origin_id}/`, completeness is detected by listing the directory, and exactly-once emission uses atomic create-if-not-exists (`open(path, "xb")`).

**How it works**:

1. Each incoming message carries an `x-asya-fan-in` header with `origin_id`, `slice_index`, `slice_count`, and `aggregation_key`
2. The handler writes each slice to `slice-{idx}.json` (unique key, no contention)
3. Slice 0 (parent payload) also saves `parent-route.json` with the continuation route
4. When all slices have arrived (detected via `os.listdir`), the handler creates a `complete` sentinel file atomically
5. The merged payload is assembled: `results[0]` is the base (parent payload), `results[1:]` are placed at `aggregation_key` (a JSON Pointer)
6. The `x-asya-fan-in` header is stripped, `x-asya-origin-id` is set, and the merged envelope is emitted

**Deployment**: Fan-in aggregator actors are generated by the flow compiler (named `fanin_{flow}_line_{N}`). Each uses the `asya_crew.fanin.split_key.aggregator` handler with a state proxy sidecar for S3 access.

## x-pause

**Responsibilities**:

- Persists the full message (metadata + headers + payload + pause metadata) to state proxy storage
- Ensures `x-resume` is the first actor in `route.next` (prepends if missing)
- Writes `x-asya-pause` header with pause metadata (prompt + fields schema)
- Returns the payload so the sidecar detects the `x-asya-pause` header and halts forwarding
- Gracefully skips persistence if `ASYA_PERSISTENCE_MOUNT` is not set

**Queue**: `asya-{namespace}-x-pause` (placed in route by flow author or dynamically via `yield "SET"`)

**Handler**: `asya_crew.pause.pause_handler` (function handler, not a generator)

**Environment Variables**:
```yaml
- name: ASYA_HANDLER
  value: asya_crew.pause.pause_handler
- name: ASYA_PERSISTENCE_MOUNT
  value: /state
- name: ASYA_PAUSE_METADATA  # optional JSON with prompt + fields schema
  value: '{"prompt": "Review this analysis", "fields": [...]}'
```

**Storage Key Structure**:
```
{mount}/paused/{message_id}.json
```

**Flow**:
1. Handler reads message metadata from VFS (id, route, headers)
2. Prepends `x-resume` to `route.next` if not already first
3. Persists full message (including `_pause_metadata`) to state proxy mount
4. Writes `x-asya-pause` header to VFS with pause metadata JSON
5. Returns payload (sidecar detects header, reports `paused` to gateway, stops routing)

## x-resume

**Responsibilities**:

- Loads persisted message from state proxy storage using task ID from `x-asya-resume-task` header
- Merges user input into restored payload using field mappings from pause metadata
- Restores `route.next` from persisted message so pipeline continues from where it paused
- Handles timeout renewal via `x-asya-resume-timeout` header (computes new `deadline_at`)
- Cleans up persisted file and header files after restoration

**Queue**: `asya-{namespace}-x-resume` (auto-prepended by x-pause if missing from route)

**Handler**: `asya_crew.resume.resume_handler` (function handler, not a generator)

**Environment Variables**:
```yaml
- name: ASYA_HANDLER
  value: asya_crew.resume.resume_handler
- name: ASYA_PERSISTENCE_MOUNT  # required
  value: /state
- name: ASYA_RESUME_MERGE_MODE  # optional: "shallow" (default) or "deep"
  value: shallow
```

**Flow**:
1. Reads task ID from `x-asya-resume-task` header
2. Loads persisted message from `{mount}/paused/{task_id}.json`
3. Merges user input: if field mappings exist, applies them at specified `payload_key` paths; otherwise does a shallow (or deep) dict merge at root
4. Writes restored `route.next` to VFS
5. If `x-asya-resume-timeout` header present, computes and writes new `deadline_at`
6. Deletes persisted file and cleanup headers
7. Returns merged payload (sidecar routes to next actor in restored route)

## Future Crew Actors

**Custom monitoring**:

- Track SLA violations per actor
- Alert on error rates and patterns
- Generate pipeline execution reports
- Aggregate metrics across messages
