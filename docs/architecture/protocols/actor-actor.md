# Actor-to-Actor Protocol

## Message Structure

**Message**: Structured JSON object transmitted through message queues (RabbitMQ, SQS), containing routing information and application data.

**Payload**: Application-specific data within message, processed by actors.

```json
{
  "id": "unique-message-id",
  "parent_id": "original-message-id",
  "route": {
    "prev": ["prep"],
    "curr": "infer",
    "next": ["post"]
  },
  "headers": {
    "trace_id": "abc-123",
    "priority": "high"
  },
  "status": {
    "phase": "pending",
    "actor": "infer",
    "attempt": 1,
    "max_attempts": 1,
    "created_at": "2025-11-18T12:00:00Z",
    "updated_at": "2025-11-18T12:00:00Z",
    "deadline_at": "2025-11-18T12:05:00Z"
  },
  "payload": {
    "text": "Hello world"
  }
}
```

**Fields**:

- `id` (required): Unique message identifier
- `parent_id` (optional): Parent message ID for fanout children (see Fan-Out section)
- `route` (required): Actor routing state
  - `prev`: Actors that have already processed the message (read-only, maintained by runtime)
  - `curr`: The actor currently processing the message (read-only, set by runtime)
  - `next`: Actors yet to process the message (modifiable via VFS)
- `status` (optional): Message lifecycle status, stamped by gateway on creation
  - `phase`: Current lifecycle phase (`pending`, `processing`, `succeeded`, `failed`)
  - `actor`: Actor that last updated the status
  - `deadline_at`: Absolute deadline in RFC3339 UTC (omitted if no timeout configured)
- `payload` (required): User data processed by actors
- `headers` (optional): Routing metadata (trace IDs, priorities)

## Queue Naming Convention

All actor queues follow pattern: `asya-{namespace}-{actor_name}`

**Examples**:
Namespace: `example-ecommerce`
- Actor `text-analyzer` → Queue `asya-example-ecommerce-text-analyzer`
- Actor `image-processor` → Queue `asya-example-ecommerce-image-processor`
- System actors: `asya-{namespace}-x-sink`, `asya-{namespace}-x-sump`

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

**`x-sink`**: Pipeline completed, aborted, or expired
- Automatically routed by sidecar when `route.curr` is `""` (route exhausted)
- Automatically routed when runtime returns empty response
- Automatically routed when `status.deadline_at` has passed (SLA expired, stamped with `phase=failed`, `reason=Timeout`)

**`x-sump`**: Processing error occurred
- Automatically routed when runtime returns error
- Automatically routed when runtime call times out (per-call timeout exceeded)

**Important**: Do not include `x-sink` or `x-sump` in route configurations - managed by sidecar.

## Response Patterns

### Single Response

Runtime returns mutated payload:
```json
{"processed": true, "timestamp": "2025-11-18T12:00:00Z"}
```

**Action**: Sidecar creates message → Runtime shifts route (prev grows, curr advances) → Routes to next actor

### Fan-Out (Generator/Yield)

Handlers use `yield` to produce multiple outputs. Each `yield` sends a frame immediately to the sidecar over the Unix socket, and the sidecar creates a separate message for routing.

```python
def process(payload):
    for item in payload["items"]:
        yield {"processed": item}
```

**Action**: Sidecar reads each yielded frame and routes it as a separate message to the next actor.

**Fanout ID semantics**:

- First yielded message retains original ID (for SSE streaming compatibility)
- Subsequent yielded messages receive suffixed IDs: `{original_id}-{index}`
- All fanout children have `parent_id` set to original message ID

**Example**: Message `abc-123` yields 3 items:

- Index 0: `id="abc-123"`, `parent_id=null` (original ID preserved)
- Index 1: `id="abc-123-1"`, `parent_id="abc-123"` (fanout child)
- Index 2: `id="abc-123-2"`, `parent_id="abc-123"` (fanout child)

**Note**: Returning a list from a handler does NOT trigger fan-out. A returned list is treated as a single payload value.

### Empty Response

Runtime returns `None` (`null`):

**Action**: Sidecar routes message to `x-sink` (no increment)

### Error Response

Runtime returns error object:
```json
{
  "error": "processing_error",
  "message": "Invalid input format"
}
```

**Action**: Sidecar routes to `x-sump` (no increment)

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
- Monotonic computation - much easier to reason about and integrate with

## Task Status Tracking

When gateway is enabled, tasks have lifecycle statuses tracked throughout processing:

### Status Values

| Status | Description | When Set |
|--------|-------------|----------|
| `pending` | Task created, not yet processing | Gateway creates task from MCP tool call |
| `running` | Task is being processed by actors | Sidecar sends first progress update |
| `succeeded` | Pipeline completed successfully | `x-sink` crew actor reports success |
| `failed` | Pipeline failed with error | `x-sump` crew actor reports failure |
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
progress_percent = (len(prev) + 1) / (len(prev) + 1 + len(next)) * 100
```

**Example**: Route starting as `{prev: [], curr: "prep", next: ["infer", "post"]}`
- Actor `prep` completed → 33%
- Actor `infer` completed → 66%
- Actor `post` completed → 100% (final status from `x-sink`)

### Progress Update Flow

```
Sidecar                    Gateway                    Client
-------                    -------                    ------
1. Receive from queue
   └─> POST /tasks/{id}/progress
       {status: "received", current_actor_idx: 0}
                           └─> Update DB: running
                           └─> SSE: progress 10%

2. Send to runtime
   └─> POST /tasks/{id}/progress
       {status: "processing", current_actor_idx: 0}
                           └─> SSE: progress 15%

3. Runtime returns
   └─> POST /tasks/{id}/progress
       {status: "completed", current_actor_idx: 0}
                           └─> SSE: progress 33%

4. Route to next actor...
```

### Final Status Reporting

**Success path**:
```
Actor N completes → Sidecar routes to x-sink
  → x-sink persists to S3
  → x-sink reports: POST /tasks/{id}/final
     {status: "succeeded", result: {...}}
  → Gateway updates: status=succeeded, progress=100%
  → SSE: final success event
```

**Error path**:
```
Runtime error → Sidecar routes to x-sump
  → x-sump persists to S3
  → x-sump reports: POST /tasks/{id}/final
     {status: "failed", error: "..."}
  → Gateway updates: status=failed
  → SSE: final error event
```

## Design Principles

- **Small payloads**: Use object storage (S3, MinIO) for large data, pass references
- **Clear names**: Use descriptive actor names (`preprocess-text` not `actor1`)
- **Monitor errors**: Alert on `x-sump` queue depth
- **Version schema**: Include version in payload for breaking changes
