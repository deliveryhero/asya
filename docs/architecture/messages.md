# Message Flow

Detailed message routing and processing flow in Asya.

## Message Structure

Every message in Asya follows this structure:

```json
{
  "route": {
    "steps": ["queue1", "queue2", "queue3"],
    "current": 0
  },
  "payload": {
    // Your application data
  }
}
```

### Fields

- **route.steps**: Array of queue names defining the processing pipeline
- **route.current**: Index of current step (auto-incremented by sidecar)
- **payload**: Arbitrary JSON data passed to runtime

## Basic Flow

### Single-Step Processing

```
Message: {
  "route": {"steps": ["process"], "current": 0},
  "payload": {"text": "Hello"}
}

Step 1 (process queue):
  ├─ Sidecar receives message
  ├─ Sends {"text": "Hello"} to runtime
  ├─ Runtime returns {"result": "Processed"}
  ├─ No more steps (current=0, steps.length=1)
  └─ Sends to happy-end queue
```

### Multi-Step Pipeline

```
Message: {
  "route": {"steps": ["preprocess", "inference", "postprocess"], "current": 0},
  "payload": {"text": "Hello"}
}

Step 1 (preprocess queue):
  ├─ Sidecar receives at current=0
  ├─ Sends {"text": "Hello"} to runtime
  ├─ Runtime returns {"tokens": [1, 2, 3]}
  ├─ Increments current to 1
  └─ Sends to "inference" queue

Step 2 (inference queue):
  ├─ Sidecar receives at current=1
  ├─ Sends {"tokens": [1, 2, 3]} to runtime
  ├─ Runtime returns {"prediction": "greeting"}
  ├─ Increments current to 2
  └─ Sends to "postprocess" queue

Step 3 (postprocess queue):
  ├─ Sidecar receives at current=2
  ├─ Sends {"prediction": "greeting"} to runtime
  ├─ Runtime returns {"output": "GREETING"}
  ├─ No more steps (current=2, steps.length=3)
  └─ Sends to happy-end queue
```

## Response Patterns

### Single Response

**Runtime returns:**
```json
{
  "status": "ok",
  "result": {"processed": true}
}
```

**Sidecar action:**
- Creates one message with `result` as new payload
- Increments route.current
- Sends to next queue

### Fan-Out (Array Response)

**Runtime returns:**
```json
{
  "status": "ok",
  "result": [
    {"chunk": 1, "text": "Hello"},
    {"chunk": 2, "text": "world"}
  ]
}
```

**Sidecar action:**
- Creates **multiple messages**, one per array item
- Each gets same route with incremented current
- All sent to next queue independently

**Example:**
```
Original: {route: {steps: ["split", "process"], current: 0}, payload: "Hello world"}

After split (returns array):
  → {route: {steps: ["split", "process"], current: 1}, payload: {"chunk": 1, "text": "Hello"}}
  → {route: {steps: ["split", "process"], current: 1}, payload: {"chunk": 2, "text": "world"}}

Both messages go to "process" queue independently.
```

### Empty Response

**Runtime returns:**
```json
{
  "status": "ok",
  "result": null
}
```

or

```json
{
  "status": "ok",
  "result": []
}
```

**Sidecar action:**
- Sends **original message** to happy-end
- No route increment
- Indicates "no further processing needed"

### Error Response

**Runtime returns:**
```json
{
  "error": "validation_error",
  "message": "Missing required field: text"
}
```

**Sidecar action:**
- Creates error message with original payload + error details
- Sends to error-end queue
- Does NOT increment route

## Terminal Queues

### happy-end

Messages sent to `happy-end` when:
- Pipeline completes successfully (no more steps)
- Runtime returns empty response
- Indicates successful completion

**Message format:**
```json
{
  "route": {
    "steps": ["step1", "step2"],
    "current": 2  // Completed all steps
  },
  "payload": {
    // Final result
  }
}
```

### error-end

Messages sent to `error-end` when:
- Runtime returns error
- Timeout occurs
- Message parsing fails
- Runtime communication fails

**Message format:**
```json
{
  "route": {
    "steps": ["step1", "step2"],
    "current": 0  // Failed at step 0
  },
  "payload": {
    // Original payload
  },
  "error": {
    "type": "runtime_error",
    "message": "Processing failed",
    "step": "step1"
  }
}
```

## Error Scenarios

### Timeout

If runtime doesn't respond within `ASYA_RUNTIME_TIMEOUT`:

```
Sidecar creates error message:
{
  "route": {...},
  "payload": <original>,
  "error": {
    "type": "timeout",
    "message": "Runtime did not respond within 5m0s"
  }
}

Sends to error-end queue
```

### Parse Error

If message structure is invalid:

```
Sidecar creates error message:
{
  "route": {"steps": ["error-end"], "current": 0},
  "payload": <original bytes>,
  "error": {
    "type": "parse_error",
    "message": "Failed to parse route: ..."
  }
}

Sends to error-end queue
```

### Runtime Error

If runtime returns error:

```json
Runtime: {
  "error": "processing_error",
  "message": "Model inference failed",
  "type": "InferenceException"
}

Sidecar wraps and sends to error-end:
{
  "route": {...},
  "payload": <original>,
  "error": {
    "type": "processing_error",
    "message": "Model inference failed",
    "exception": "InferenceException"
  }
}
```

## Complete Example

### 3-Step Pipeline with Fan-Out

**Initial Message:**
```json
{
  "route": {
    "steps": ["tokenize", "process-tokens", "aggregate"],
    "current": 0
  },
  "payload": {
    "text": "Hello world"
  }
}
```

**Step 1: tokenize**
```
Queue: tokenize
Current: 0

Runtime receives: {"text": "Hello world"}
Runtime returns: {
  "status": "ok",
  "result": [
    {"token": "Hello", "id": 1},
    {"token": "world", "id": 2}
  ]
}

Sidecar creates 2 messages:
  1. {route: {steps: [...], current: 1}, payload: {"token": "Hello", "id": 1}}
  2. {route: {steps: [...], current: 1}, payload: {"token": "world", "id": 2}}

Both sent to "process-tokens" queue
```

**Step 2: process-tokens (runs twice, in parallel)**
```
Message 1:
  Queue: process-tokens
  Current: 1
  Runtime receives: {"token": "Hello", "id": 1}
  Runtime returns: {"processed": "HELLO", "id": 1}
  Sent to "aggregate" queue

Message 2:
  Queue: process-tokens
  Current: 1
  Runtime receives: {"token": "world", "id": 2}
  Runtime returns: {"processed": "WORLD", "id": 2}
  Sent to "aggregate" queue
```

**Step 3: aggregate (runs twice)**
```
Message 1:
  Queue: aggregate
  Current: 2
  Runtime receives: {"processed": "HELLO", "id": 1}
  Runtime returns: {"final": "HELLO"}
  No more steps → sent to happy-end

Message 2:
  Queue: aggregate
  Current: 2
  Runtime receives: {"processed": "WORLD", "id": 2}
  Runtime returns: {"final": "WORLD"}
  No more steps → sent to happy-end
```

**Result:**
- 2 messages in happy-end queue
- Each represents one processed token
- Original message split into parallel processing paths

## Gateway Integration

When using the Asya Gateway:

**Initial Request:**
```
Client → Gateway (MCP call)
```

**Gateway Creates:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "route": {
    "steps": ["step1", "step2"],
    "current": 0
  },
  "payload": {
    "input": "user data"
  }
}
```

**Processing:**
```
step1 → step2 → happy-end
         │
         └─ Gateway monitors job_id
            Updates job status: Pending → Running → Succeeded
```

**Client Access:**
```
GET /jobs/{job_id}/stream → SSE updates
GET /jobs/{job_id} → Final status
```

## Best Practices

### Route Design

1. **Keep steps focused**: Each step should do one thing
2. **Use fan-out judiciously**: Consider queue depth implications
3. **Handle errors explicitly**: Don't assume success
4. **Name queues clearly**: `preprocess-text`, not `step1`

### Payload Design

1. **Keep payloads small**: Large data should use object storage
2. **Include context**: Enough info for each step to process independently
3. **Use consistent schema**: Makes debugging easier
4. **Version payloads**: Include version field for breaking changes

### Error Handling

1. **Monitor error-end**: Set up alerts
2. **Include context**: Original payload + error details
3. **Make errors actionable**: Clear error messages
4. **Consider retry logic**: Some errors are transient

## Next Steps

- [Sidecar Architecture](sidecar.md) - Detailed sidecar design
- [Runtime Component](../components/runtime.md) - Runtime implementation
- [Architecture Overview](overview.md) - System architecture
