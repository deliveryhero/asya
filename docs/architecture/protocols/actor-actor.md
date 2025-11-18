# Actor-to-Actor Protocol

## Message vs Envelope

**Message**: Raw bytes transmitted through message queue (RabbitMQ, SQS).

**Envelope**: Structured JSON object parsed from queue bytes, containing routing information and application data.

**Payload**: Application-specific data within envelope, processed by actors.

## Envelope Structure

```json
{
  "id": "unique-envelope-id",
  "parent_id": "original-envelope-id",
  "route": {
    "actors": ["prep", "infer", "post"],
    "current": 0
  },
  "headers": {
    "trace_id": "abc-123",
    "priority": "high"
  },
  "payload": {
    "text": "Hello world"
  }
}
```

**Fields**:

- `id` (required): Unique envelope identifier
- `parent_id` (optional): Parent envelope ID for fanout children (see Fan-Out section)
- `route` (required): Actor list and current position
  - `actors`: Pipeline definition
  - `current`: Current actor index (0-based, incremented by runtime)
- `payload` (required): User data processed by actors
- `headers` (optional): Routing metadata (trace IDs, priorities)

## Queue Naming Convention

All actor queues follow pattern: `asya-{actor_name}`

**Examples**:

- Actor `text-analyzer` → Queue `asya-text-analyzer`
- Actor `image-processor` → Queue `asya-image-processor`
- System actors: `asya-happy-end`, `asya-error-end`

**Benefits**:

- Fine-grained IAM policies: `arn:aws:sqs:*:*:asya-*`
- Clear namespace separation
- Automated queue management by operator

## Message Acknowledgment

**Ack**: Message processed successfully, remove from queue
- Runtime returns valid response
- Sidecar routes to next actor or end queue

**Nack**: Message processing failed in sidecar, requeue
- Sidecar crashes before processing
- Queue automatically sends to DLQ after max retries

## End Queues

**`happy-end`**: Pipeline completed or aborted successfully
- Automatically routed by sidecar when no more actors in route
- Automatically routed when runtime returns empty response

**`error-end`**: Processing error occurred
- Automatically routed when runtime returns error
- Automatically routed on timeout

**Important**: Do not include `happy-end` or `error-end` in route configurations - managed by sidecar.

## Response Patterns

### Single Response

Runtime returns mutated payload:
```json
{"processed": true, "timestamp": "2025-11-18T12:00:00Z"}
```

**Action**: Sidecar creates envelope → Increments current → Routes to next actor

### Fan-Out (Array)

Runtime returns array:
```json
[
  {"chunk": 1, "text": "Hello"},
  {"chunk": 2, "text": "world"}
]
```

**Action**: Sidecar creates multiple envelopes (one per item) → Routes to next actor

**Fanout ID semantics**:

- First envelope retains original ID (for SSE streaming compatibility)
- Subsequent envelopes receive suffixed IDs: `{original_id}-{index}`
- All fanout children have `parent_id` set to original envelope ID

**Example**: Envelope `abc-123` returns 3 items:

- Index 0: `id="abc-123"`, `parent_id=null` (original ID preserved)
- Index 1: `id="abc-123-1"`, `parent_id="abc-123"` (fanout child)
- Index 2: `id="abc-123-2"`, `parent_id="abc-123"` (fanout child)

### Empty Response

Runtime returns `null` or `[]`:

**Action**: Sidecar routes envelope to `happy-end` (no increment)

### Error Response

Runtime returns error object:
```json
{
  "error": "processing_error",
  "message": "Invalid input format"
}
```

**Action**: Sidecar routes to `error-end` (no increment)

## Payload Enrichment Pattern

**Recommended**: Actors append results to payload instead of replacing it.

**Example pipeline**: `["data-loader", "recipe-generator", "llm-judge"]`

```json
// Input to data-loader
{"product_id": "123"}

// Output of data-loader → Input to recipe-generator
{
  "product_id": "123",
  "product_name": "Ice-cream Bourgignon"
}

// Output of recipe-generator → Input to llm-judge
{
  "product_id": "123",
  "product_name": "Ice-cream Bourgignon",
  "recipe": "Cook ice-cream in tomato sauce for 3 hours"
}

// Output of llm-judge → Final result
{
  "product_id": "123",
  "product_name": "Ice-cream Bourgignon",
  "recipe": "Cook ice-cream in tomato sauce for 3 hours",
  "recipe_eval": "INVALID",
  "recipe_eval_details": "Recipe is nonsense"
}
```

**Benefits**:

- Better actor decoupling - each actor only needs specific fields
- Full traceability - complete processing history in final payload
- Routing flexibility - later actors can access earlier results

## Envelope Status Tracking

When gateway is enabled, envelopes have lifecycle statuses tracked throughout processing:

### Status Values

| Status | Description | When Set |
|--------|-------------|----------|
| `pending` | Envelope created, not yet processing | Gateway creates envelope from MCP tool call |
| `running` | Envelope is being processed by actors | Sidecar sends first progress update |
| `succeeded` | Pipeline completed successfully | `happy-end` crew actor reports success |
| `failed` | Pipeline failed with error | `error-end` crew actor reports failure |
| `unknown` | Status cannot be determined | Edge cases, missing updates |

### Progress Reporting

Sidecars report progress to gateway at three points per actor:

**1. Received** (`received`):

- Message pulled from queue
- Before forwarding to runtime

**2. Processing** (`processing`):

- Message sent to runtime via Unix socket
- Runtime is executing handler

**3. Completed** (`completed`):

- Runtime returned successful response
- Before routing to next actor

**Progress calculation**:
```
progress_percent = (actors_completed / total_actors) * 100
```

**Example**: Route `["prep", "infer", "post"]` (3 actors)
- Actor `prep` completed → 33%
- Actor `infer` completed → 66%
- Actor `post` completed → 100% (final status from `happy-end`)

### Progress Update Flow

```
Sidecar                    Gateway                    Client
-------                    -------                    ------
1. Receive from queue
   └─> POST /envelopes/{id}/progress
       {status: "received", current_actor_idx: 0}
                           └─> Update DB: running
                           └─> SSE: progress 10%

2. Send to runtime
   └─> POST /envelopes/{id}/progress
       {status: "processing", current_actor_idx: 0}
                           └─> SSE: progress 15%

3. Runtime returns
   └─> POST /envelopes/{id}/progress
       {status: "completed", current_actor_idx: 0}
                           └─> SSE: progress 33%

4. Route to next actor...
```

### Final Status Reporting

**Success path**:
```
Actor N completes → Sidecar routes to happy-end
  → happy-end persists to S3
  → happy-end reports: POST /envelopes/{id}/final
     {status: "succeeded", result: {...}}
  → Gateway updates: status=succeeded, progress=100%
  → SSE: final success event
```

**Error path**:
```
Runtime error → Sidecar routes to error-end
  → error-end persists to S3
  → error-end reports: POST /envelopes/{id}/final
     {status: "failed", error: "..."}
  → Gateway updates: status=failed
  → SSE: final error event
```

## Design Principles

- **Small payloads**: Use object storage (S3, MinIO) for large data, pass references
- **Clear names**: Use descriptive actor names (`preprocess-text` not `actor1`)
- **Monitor errors**: Alert on `error-end` queue depth
- **Version schema**: Include version in payload for breaking changes
