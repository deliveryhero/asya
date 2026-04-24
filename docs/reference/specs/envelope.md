---
description: "Envelope spec: JSON structure, route (prev/curr/next), headers, status, fan-out ID semantics"
---

# Envelope

## Envelope Structure

**Envelope**: Structured JSON object transmitted through message queues (RabbitMQ, SQS), containing routing information and application data.

**Payload**: Application-specific data within envelope, processed by actors.

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

- `id` (required): Unique envelope identifier
- `parent_id` (optional): Parent envelope ID for fanout children (see Fan-Out section)
- `route` (required): Actor routing state
  - `prev`: Actors that have already processed the envelope (read-only, maintained by runtime)
  - `curr`: The actor currently processing the envelope (read-only, set by runtime)
  - `next`: Actors yet to process the envelope (modifiable via ABI)
- `status` (optional): Envelope lifecycle status, stamped by gateway on creation
  - `phase`: Current lifecycle phase (`pending`, `processing`, `retrying`, `succeeded`, `failed`, `paused`, `canceled`)
  - `actor`: Actor that last updated the status
  - `deadline_at`: Absolute deadline in RFC3339 UTC (omitted if no timeout configured)
- `payload` (required): User data processed by actors
- `headers` (optional): Routing metadata (trace IDs, priorities)

### Envelope Status Ordering

The mesh-api enforces monotonic status progression. When a status event arrives, the mesh-api compares it against the current status and silently drops stale updates:

| Order | Statuses | Description |
|-------|----------|-------------|
| 0 | `pending` | Created, not yet picked up |
| 1 | `running` | Being processed by an actor (sidecar `received`/`processing`/`completed` events all map here) |
| 2 | `paused` | Waiting for external input (HITL) |
| 3 | `succeeded`, `failed`, `canceled` | Terminal — no further transitions |

**Valid transitions**:
```
pending → running → succeeded
pending → running → failed
pending → running → paused → running → succeeded
```

Status never goes backward. Terminal statuses (`succeeded`, `failed`, `canceled`) are all order 3 — once terminal, no other status can overwrite. If two `running` updates arrive simultaneously, the second overwrites with the same value (idempotent). FLY events have no ordering constraint — they are appended in arrival order.

### Sidecar-Managed Headers

These headers are automatically managed by the sidecar and should not be
overwritten by user handlers:

| Header | Description |
|---|---|
| `traceparent` | W3C Trace Context parent (auto-injected when tracing enabled) |
| `tracestate` | W3C Trace Context state (auto-injected when tracing enabled) |
| `x-asya-first-attempt` | RFC3339 timestamp of the first processing attempt (stamped on first attempt, preserved across retries; used for `maxDuration` evaluation) |

### Gateway-Stamped Headers

These headers are stamped by the gateway when creating the envelope and read
by the sidecar during processing:

| Header | Description |
|---|---|
| `x-asya-gateway-url` | Internal gateway URL for sidecar callbacks. Stamped by the gateway dispatcher. Sidecar uses this for progress reporting, event posting, and pre-flight checks. Falls back to `ASYA_GATEWAY_URL` env var if absent. Validated against SSRF: only `http`/`https` schemes with non-empty hosts are accepted. |
| `x-asya-mesh-status` | Set to `"off"` to suppress all gateway status reporting for this envelope (stealth mode). |

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

## Envelope Acknowledgment

**Ack**: Envelope processed successfully, remove from queue
- Runtime returns valid response
- Sidecar routes to next actor or end queue

**Nack**: Envelope processing failed in sidecar, requeue
- Sidecar crashes before processing
- Queue automatically sends to DLQ after max retries

## End Queues

**`x-sink`**: First layer of termination. Receives ALL terminal envelopes — both succeeded and failed. Routed by sidecar when route is exhausted (success), when SLA expires, or when resiliency policy is exhausted (failure). Reports final status to gateway, dispatches to hooks.

**`x-sump`**: Dead-letter queue (final terminal). Receives envelopes from two paths:

1. **From `x-sink`** — after hook processing for handler-level failures
2. **Directly from sidecar** — for infrastructure errors (timeouts, runtime crashes, parse errors, route mismatches) that bypass `x-sink` entirely

Emits metrics and logs errors. The sidecar routes directly to `x-sump` when the error cannot be handled by the resiliency policy.

**Important**: Do not include `x-sink` or `x-sump` in route configurations - managed by sidecar.

## Response Patterns

### Single Response

Runtime returns mutated payload:
```json
{"processed": true, "timestamp": "2025-11-18T12:00:00Z"}
```

**Action**: Sidecar creates envelope → Runtime shifts route (prev grows, curr advances) → Routes to next actor

### Fan-Out (Generator/Yield)

Handlers use `yield` to produce multiple outputs. Each `yield` sends a frame immediately to the sidecar over the Unix socket, and the sidecar creates a separate message for routing.

```python
async def process(payload):
    for item in payload["items"]:
        yield {"processed": item}
```

**Action**: Sidecar reads each yielded frame and routes it as a separate envelope to the next actor.

**Fanout ID semantics**:

- First yielded envelope retains original ID (for SSE streaming compatibility)
- Subsequent yielded envelopes receive UUID4 IDs (globally unique, no collision across concurrent fan-outs)
- All fanout children (index > 0) have `parent_id` set to original envelope ID

**Example**: Envelope `abc-123` yields 3 items:

- Index 0: `id="abc-123"`, `parent_id=null` (original ID preserved)
- Index 1: `id="550e8400-e29b-41d4-a716-446655440000"`, `parent_id="abc-123"` (fanout child, UUID4)
- Index 2: `id="7c9e6679-7425-40de-944b-e07fc1f90ae7"`, `parent_id="abc-123"` (fanout child, UUID4)

**Note**: Returning a list from a handler does NOT trigger fan-out. A returned list is treated as a single payload value.

### Empty Response

Runtime returns `None` (`null`):

**Action**: Sidecar routes envelope to `x-sink` (no increment)

### Error Response

Runtime returns error object:
```json
{
  "error": "processing_error",
  "message": "Invalid input format"
}
```

**Action**: Sidecar applies resiliency policy: retries if configured, or routes to `x-sink` (phase: failed) if exhausted/non-retryable.

**Infrastructure errors** (timeout, runtime crash, parse error, route mismatch) bypass resiliency and route directly to `x-sump`.

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
| `running` | Task is being processed by actors | Sidecar sends first progress update (maps `received`/`processing`/`completed` sidecar events) |
| `succeeded` | Pipeline completed successfully | `x-sink` crew actor reports success |
| `failed` | Pipeline failed with error | `x-sink` crew actor reports failure (or gateway backstop timer) |
| `paused` | Waiting for external input | Sidecar detects `x-asya-pause` header from x-pause crew actor |
| `canceled` | Task was canceled | Client cancels via `POST /a2a/tasks/{id}:cancel` |
| `unknown` | Status cannot be determined | Edge cases, missing updates |

### Progress Reporting

Sidecars report progress to gateway at three points per actor:

**1. Received** (`received`):

- Envelope pulled from queue
- Before forwarding to runtime

**2. Processing** (`processing`):

- Envelope sent to runtime via Unix socket
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

All sidecar-to-gateway communication uses the unified events endpoint
`POST /api/v1/mesh/{id}/events`.

```
Sidecar                    Gateway                    Client
-------                    -------                    ------
0. Pre-flight check
   └─> GET /api/v1/mesh/{id}
       If canceled/paused → route to x-sink, skip processing

1. Receive from queue
   └─> POST /api/v1/mesh/{id}/events
       {type: "status", status: "received", data: {...}}
                           └─> Update DB: running
                           └─> SSE: progress 10%

2. Send to runtime
   └─> POST /api/v1/mesh/{id}/events
       {type: "status", status: "processing", data: {...}}
                           └─> SSE: progress 15%

3. Runtime streams FLY tokens
   └─> POST /api/v1/mesh/{id}/events
       {type: "fly", data: {"text": "token..."}}
                           └─> SSE: partial event (ephemeral)

4. Runtime returns
   └─> POST /api/v1/mesh/{id}/events
       {type: "status", status: "completed", data: {...}}
                           └─> SSE: progress 33%

5. Route to next actor...
```

### Final Status Reporting

**Success path**:
```
Actor N completes → Sidecar routes to x-sink
  → x-sink persists to S3
  → x-sink reports: POST /api/v1/mesh/{id}/events
     {type: "status", status: "succeeded", data: {...}}
  → Gateway updates: status=succeeded, progress=100%
  → SSE: final success event
```

**Error path**:
```
Runtime error → Sidecar retries per resiliency policy
  → If exhausted/non-retryable → Sidecar routes to x-sink (phase: failed)
  → x-sink reports: POST /api/v1/mesh/{id}/events
     {type: "status", status: "failed", data: {...}}
  → x-sink dispatches to hooks → x-sump (final terminal)
  → Gateway updates: status=failed
  → SSE: final error event
```

## Design Principles

- **Small payloads**: Use object storage (S3, MinIO) for large data, pass references
- **Clear names**: Use descriptive actor names (`preprocess-text` not `actor1`)
- **Monitor errors**: Alert on `x-sump` queue depth
- **Version schema**: Include version in payload for breaking changes
