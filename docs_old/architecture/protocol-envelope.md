# Envelope Flow

## Terminology

To avoid confusion, Asya🎭 uses precise terminology to distinguish between different layers of the messaging system:

### Message (Queue Message)
**Definition**: Raw bytes transmitted through the message queue (RabbitMQ, SQS, etc.)

**Usage**:
- Low-level queue operations
- Variable name: `msg` (type: `QueueMessage` interface)
- Examples: `msg.Body()`, `msg.DeliveryTag()`

**Code representation**:
```go
type QueueMessage interface {
    Body() []byte          // Raw message bytes
    DeliveryTag() uint64   // Queue-specific delivery tracking
}
```

**When "message" is used**:
- Queue client operations: `Receive()`, `Ack()`, `Nack()`
- Transport layer abstractions
- Comments about queue mechanics

### Envelope
**Definition**: Structured message parsed from queue bytes, containing routing information and application data

**Usage**:
- Business logic layer after parsing
- Variable name: `envelope` (type: `Envelope` struct)
- Contains: `id`, `route`, `headers`, `payload`

**Code representation**:
```go
type Envelope struct {
    ID       string          `json:"id"`
    Route    Route           `json:"route"`
    Headers  map[string]any  `json:"headers,omitempty"`
    Payload  json.RawMessage `json:"payload"`
}
```

**When "envelope" is used**:
- After parsing queue message bytes
- Router logic and business operations
- Progress tracking and state management

### Payload
**Definition**: Application-specific data within an envelope, processed by actors

**Usage**:
- The actual business data that actors transform
- Is NOT a request or response payload - mutates from actor to actor
- Type: `json.RawMessage` (arbitrary JSON)
- Actors receive only the payload (in payload mode) or full envelope (in envelope mode)

**Examples**:
```json
{"text": "Hello world"}                    // Simple payload
{"image_url": "s3://...", "model": "v2"}  // ML inference payload
[{"chunk": 1}, {"chunk": 2}]              // Fan-out payload
```

### Route
**Definition**: Routing metadata defining the actor pipeline

**Usage**:
- Determines which actors process the envelope
- Sidecar auto-increments `current` after each actor
- Variable name: `route` (type: `Route` struct)
- By default, not processed by actor handler (unless the runtime sets `ASYA_HANDLER_MODE="envelope"`)

**Code representation**:
```go
type Route struct {
    Actors   []string       `json:"actors"`   // Pipeline: ["prep", "infer", "post"]
    Current  int            `json:"current"`  // Current actor index (0-based)
    Metadata map[string]any `json:"metadata,omitempty"` // Optional routing hints
}
```

### Headers
**Definition**: Optional routing-specific metadata (distinct from payload)

**Usage**:
- Cross-cutting concerns: trace IDs, priorities, deadlines, A/B mark, etc
- Preserved across pipeline actors
- By default, not processed by actor handler (unless the runtime sets `ASYA_HANDLER_MODE="envelope"`)

**Examples**:
```json
{
  "trace_id": "abc-123-def",
  "priority": "high",
  "test_mode": "e2e", // for marking envelope as end-to-end test
  "retry_count": 2
}
```

### Summary Table

| Term | Layer | Type | Contains | Used By |
|------|-------|------|----------|---------|
| **Message** | Transport | `[]byte` | Raw queue bytes | Queue client, transport |
| **Envelope** | Business | `Envelope` | id, route, headers, payload | Sidecar, gateway, actors |
| **Payload** | Application | `json.RawMessage` | Business data | Actor runtime handlers |
| **Route** | Routing | `Route` | actors[], current | Sidecar routing logic |
| **Headers** | Metadata | `map[string]any` | Trace IDs, priorities | Progress tracking, observability |

### Flow: Message → Envelope → Payload

```
1. Queue bytes (message)
   └─> Unmarshal ──> Envelope {id, route, headers, payload}
                      └─> Extract ──> Payload (sent to actor runtime)
                                      └─> Transform ──> New Payload
                      └─> Update route.current
   └─> Marshal ──> Queue bytes (message to next actor)
```

## Envelope Structure

```json
{
  "id": "<envelope-id>",
  "route": {
    "actors": ["actor1", "actor2", "actor3"],
    "current": 0
  },
  "headers": {
    "trace_id": "...",
    "priority": "high"
  },
  "payload": {
    // Your application data
  }
}
```

**Fields:**
- `id`: Unique envelope identifier
- `route.actors`: Actor names defining the pipeline
- `route.current`: Current actor index (auto-incremented by sidecar)
- `headers` (optional): Routing-specific metadata (trace IDs, priorities, etc.)
- `payload`: Arbitrary JSON data processed by actors

## Flow Examples

### Single Actor

```
{"id": "env-123", "route": {"actors": ["processor"], "current": 0}, "payload": {"text": "Hello"}}

process actor:
  1. Sidecar receives envelope → Sends payload {"text": "Hello"} to runtime
  2. Runtime returns mutated payload {"result": "Processed"}
  3. Sidecar creates envelope with new payload → No more actors → Sends to happy-end
```

### Multi-Actor Pipeline

```
{"id": "env-456", "route": {"actors": ["prep", "infer", "post"], "current": 0}, "payload": {"text": "Hi"}}

prep actor (current=0):
  Runtime returns {"tokens": [1,2]} → Sidecar increments to 1 → Routes to "infer"

infer actor (current=1):
  Runtime returns {"prediction": "greeting"} → Sidecar increments to 2 → Routes to "post"

post actor (current=2):
  Runtime returns {"output": "GREETING"} → No more actors → Sidecar routes to happy-end
```

## Response Patterns

### Single Response

Runtime returns mutated payload: `{"processed": true, "timestamp": "2025-10-24T12:00:00Z"}`

Action: Sidecar creates envelope with new payload → Increments current → Routes to next actor

### Fan-Out (Array)

Runtime returns array payload: `[{"chunk": 1}, {"chunk": 2}]`

Action: Sidecar creates multiple envelopes (one per item) → Increments current → Routes each to next actor

Example:
```
Input: {id: "env-789", route: {actors: ["split", "process"], current: 0}, payload: {"text": "Hello world"}}

split runtime returns: [{"text": "Hello"}, {"text": "world"}]

Output (2 envelopes):
  {id: "env-789-0", route: {actors: ["split", "process"], current: 1}, payload: {"text": "Hello"}}
  {id: "env-789-1", route: {actors: ["split", "process"], current: 1}, payload: {"text": "world"}}
```

### Empty Response

Runtime returns: `null` or `[]`

Action: Sidecar sends original envelope to happy-end (no increment)

### Error Response

Runtime returns: `{"error": "validation_error", "message": "..."}`

Action: Sidecar creates error envelope → Sends to error-end (no increment)

## End Queues

**happy-end**: Pipeline complete or empty response (automatically routed by sidecar)

**error-end**: Runtime error, timeout, or parse failure (automatically routed by sidecar)

**IMPORTANT**: Never include `happy-end` or `error-end` in route configurations - they are managed automatically by the sidecar.

Error envelope format:
```json
{
  "id": "<envelope-id>",
  "route": {...},
  "payload": <original>,
  "error": {"type": "...", "message": "..."}
}
```

## Gateway Integration

```
Client → Gateway (MCP) → Creates envelope (pending)
  → actor1 → actor2 → happy-end → Reports to gateway (succeeded/failed)

Client polls: GET /envelopes/{id} or streams: GET /envelopes/{id}/stream
```

## Design Principles

- **Small payloads**: Use object storage for large data
- **Clear names**: `preprocess-text` not `actor1`
- **Monitor errors**: Alert on error-end queue depth
- **Version schema**: Include version in payload for breaking changes

## Next steps

- [Sidecar Component](asya-sidecar.md) - Detailed sidecar design
- [Runtime Component](asya-runtime.md) - Runtime implementation
- [Architecture Overview](README.md) - System architecture
