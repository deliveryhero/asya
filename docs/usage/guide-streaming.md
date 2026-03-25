# Streaming

How to stream live progress updates from your actor handlers to gateway clients in real-time.

---

## What are FLY events?

FLY events are **ephemeral streaming messages** sent upstream from your actor handler to the gateway. They bypass message queues and are delivered directly to connected clients via Server-Sent Events (SSE).

Think of FLY as the **fast lane** for live updates:

- **FLY events**: Real-time, ephemeral, reach only connected SSE clients
- **Payload data**: Persistent, routed through queues, visible to all downstream actors

Use FLY for:
- Streaming LLM tokens as they're generated
- Progress updates (`"Processing chunk 3/10..."`)
- Live status messages (`"Connecting to database..."`, `"Model loaded"`)
- Debug markers during development

Do NOT use FLY for:
- Data that downstream actors need to read
- Information that must survive pause/resume
- Final results (use `yield payload` instead)

---

## How to use FLY

FLY is an ABI verb. Yield a tuple with `"FLY"` as the first element and a dict as the second:

```python
async def my_handler(payload: dict):
    # Stream a status update
    yield "FLY", {"type": "status", "message": "Starting processing..."}

    # Do work
    result = await process_data(payload["input"])

    # Emit final result downstream
    payload["result"] = result
    yield payload
```

### Signature

```python
yield "FLY", <dict>
```

The dict can contain any JSON-serializable data. Common patterns:

```python
# Status update
yield "FLY", {"type": "status", "message": "Loading model..."}

# Progress percentage
yield "FLY", {"type": "progress", "percent": 45, "step": "preprocessing"}

# LLM token (partial=True mirrors Google ADK's Event(partial=True))
yield "FLY", {"partial": True, "text": "Hello"}
```

---

## FLY vs History

FLY events are **ephemeral** — they reach only clients connected at the moment they're sent. If a client disconnects and reconnects, FLY events are gone.

For data that must survive pause/resume or be readable by downstream actors, append to `payload.a2a.task.history[]` instead:

```python
async def analyst(payload: dict):
    # Ephemeral streaming (live clients only)
    yield "FLY", {"type": "status", "message": "Analyzing risk..."}

    result = await analyze_risk(payload)

    # Persistent history (survives pause/resume, visible to downstream)
    if "a2a" not in payload:
        payload["a2a"] = {}
    if "task" not in payload["a2a"]:
        payload["a2a"]["task"] = {}
    if "history" not in payload["a2a"]["task"]:
        payload["a2a"]["task"]["history"] = []

    payload["a2a"]["task"]["history"].append({
        "timestamp": datetime.utcnow().isoformat(),
        "actor": "analyst",
        "event": "risk_analysis_complete",
        "data": {"risk_level": result["risk_level"]}
    })

    payload["result"] = result
    yield payload
```

| Use case | FLY | History |
|----------|-----|---------|
| Live token streaming (LLMs) | ✅ | ❌ |
| Progress bars for connected clients | ✅ | ❌ |
| Debug logs during development | ✅ | ❌ |
| Audit trail (who did what when) | ❌ | ✅ |
| Data for downstream actors | ❌ | ✅ |
| Data that survives pause/resume | ❌ | ✅ |

---

## Common Patterns

### 1. Streaming LLM tokens

Stream tokens as they're generated, then send the complete response downstream:

```python
async def llm_handler(payload: dict):
    tokens = []

    async for token in call_llm_stream(payload["prompt"]):
        # partial=True mirrors ADK's Event(partial=True, content=Part(text=token))
        yield "FLY", {"partial": True, "text": token}
        tokens.append(token)

    # Final response (non-partial)
    payload["response"] = "".join(tokens)
    yield payload
```

**ADK equivalent**:

```python
# Google ADK
async for token in llm.stream(prompt):
    yield Event(partial=True, content=Part(text=token))
yield Event(partial=False, content=Part(text=full_response))
```

**Asya**:

```python
# Asya
async for token in llm.stream(prompt):
    yield "FLY", {"partial": True, "text": token}
yield payload  # downstream frame is the final (non-partial) event
```

### 2. Progress updates for long-running jobs

```python
async def batch_processor(payload: dict):
    items = payload["items"]
    total = len(items)
    results = []

    for i, item in enumerate(items):
        # Stream progress
        percent = int((i / total) * 100)
        yield "FLY", {
            "type": "progress",
            "percent": percent,
            "current": i + 1,
            "total": total,
            "message": f"Processing item {i+1}/{total}"
        }

        result = await process_item(item)
        results.append(result)

    payload["results"] = results
    yield payload
```

### 3. Multi-stage status updates

```python
async def data_pipeline(payload: dict):
    yield "FLY", {"stage": "download", "message": "Downloading data..."}
    data = await download(payload["url"])

    yield "FLY", {"stage": "validate", "message": "Validating schema..."}
    validated = await validate(data)

    yield "FLY", {"stage": "transform", "message": "Transforming data..."}
    transformed = await transform(validated)

    yield "FLY", {"stage": "upload", "message": "Uploading results..."}
    result_url = await upload(transformed)

    payload["result_url"] = result_url
    yield payload
```

### 4. Debug markers

```python
async def debug_handler(payload: dict):
    yield "FLY", {"debug": "handler_start", "payload_keys": list(payload.keys())}

    intermediate = await step_one(payload)
    yield "FLY", {"debug": "step_one_complete", "output": intermediate}

    final = await step_two(intermediate)
    yield "FLY", {"debug": "step_two_complete", "output": final}

    payload["result"] = final
    yield payload
```

---

## How FLY reaches clients

```
Actor handler
    yield "FLY", {...}
         │
         ▼
    Runtime
         │ sends FLY frame over Unix socket
         ▼
    Sidecar
         │ HTTP POST /mesh/{task_id}/fly
         ▼
    Gateway (mesh mode)
         │ broadcasts via pg_notify (no DB write)
         ▼
    PG LISTEN/NOTIFY
         │ cross-process delivery
         ▼
    Gateway (api mode)
         │ in-process subscribers
         ▼
    Connected SSE clients (/stream/{id} or /mesh/{id}/stream)
```

FLY events bypass message queues entirely — they travel from the sidecar directly to the mesh gateway via HTTP, then are broadcast to the API gateway via PG LISTEN/NOTIFY (in-memory, no disk persistence), and finally streamed to SSE clients. This makes them fast but ephemeral — clients connecting after task completion will NOT see historical FLY events.

---

## MCP vs A2A: when to use which

Both protocols expose your flows to external clients, but they serve different
audiences and have different streaming semantics.

| Aspect | MCP | A2A |
|--------|-----|-----|
| **Audience** | LLM clients, developer tools | AI agents, orchestrators |
| **Interaction** | Tool invocation (call + result) | Task lifecycle (send, subscribe, cancel) |
| **Streaming** | SSE on same connection | SSE via subscribe endpoint |
| **FLY events** | Delivered as `event: partial` (or `artifact_update`/`status_update` if payload matches A2A shapes) | Same SSE event types |
| **Session** | Requires MCP session (initialize handshake) | Stateless per-request |
| **Pause/resume** | Not supported | Built-in (`input_required` state) |
| **Multi-turn** | Not natively supported | Context ID tracks conversation |

**Use MCP when:**
- Building LLM tool integrations (Claude, GPT, Gemini)
- Your flow is a single request-response operation
- You want standard MCP client compatibility

**Use A2A when:**
- Building agent-to-agent communication
- Your flow involves pause/resume (human-in-the-loop)
- You need multi-turn conversations
- You want structured streaming with `TaskArtifactUpdateEvent`

**Use both when:**
- You want maximum interoperability

Register your flow with both protocols:

```bash
asya expose my-flow -d "Description" --mcp --a2a
```

### FLY event shapes for A2A compatibility

If you want FLY events to appear as standard A2A SSE event types (not just
`event: partial`), structure the payload with the appropriate top-level key:

```python
# Standard A2A artifact streaming (event type: artifact_update)
yield "FLY", {
    "artifact_update": {
        "artifact": {
            "parts": [{"kind": "text", "text": "token"}]
        }
    }
}

# Standard A2A status update (event type: status_update)
yield "FLY", {
    "status_update": {
        "state": "working",
        "message": {"role": "agent", "parts": [{"kind": "text", "text": "Processing..."}]}
    }
}

# Non-standard (event type: partial) — works with custom clients
yield "FLY", {"partial": True, "text": "token"}
```

---

## Dual-gateway streaming latency

In dual-gateway mode (separate api + mesh pods), FLY events are relayed
via PostgreSQL:

```
Sidecar ---POST /mesh/{id}/fly---> Gateway mesh
                                       |
                                   writes to PostgreSQL
                                       |
Gateway api <---polls DB (500ms)-------+
    |
SSE client
```

This adds up to **500ms latency** per FLY event. For progress updates and
stage transitions this is acceptable. For per-token LLM streaming
(~30 tokens/sec), events arrive in batches rather than individually.

**Workarounds:**
- Run in **single-gateway mode** (api + mesh in one pod) for near-zero FLY
  latency via in-process channels
- A future improvement will add a direct pub/sub relay (Redis/NATS) between
  mesh and api pods for sub-millisecond FLY delivery (see aint `debt/jhre`)

---

## Client-side consumption

### Protocol-agnostic SSE

Connect to `/stream/{task_id}` (API gateway) for protocol-agnostic FLY event streaming:

```bash
curl -N -H "Accept: text/event-stream" \
  http://gateway/stream/{task_id}
```

Or use `/mesh/{task_id}/stream` (mesh gateway) for internal mesh access:

```bash
curl -N -H "Accept: text/event-stream" \
  http://gateway/mesh/{task_id}/stream
```

Stream format:

```
event: partial
data: {"partial":true,"text":"Hello"}

event: partial
data: {"partial":true,"text":" world"}

event: update
data: {"id":"task-123","status":"succeeded","result":{...}}
```

FLY events arrive with `event: partial` by default. If the FLY payload contains A2A-specific keys (`artifact_update`, `status_update`, or `message`), the event type matches that key instead. Progress updates from the sidecar arrive with `event: update`. The final result arrives as the last `update` event with `status: succeeded`.

### A2A Subscribe

A2A clients receive FLY events via the Subscribe RPC:

```json
{
  "jsonrpc": "2.0",
  "method": "subscribe",
  "params": {"task_id": "task-123"}
}
```

Response stream:

```json
{"type": "fly", "data": {"partial": true, "text": "Hello"}}
{"type": "fly", "data": {"partial": true, "text": " world"}}
{"type": "update", "status": "succeeded", "result": {...}}
```

---

## Testing FLY locally

FLY events are filtered out by the `actor()` test wrapper (they're tuples, not dicts). To verify FLY emissions in tests, collect all yields:

```python
async def collect_all(gen):
    """Collect all yields: both ABI commands and emitted frames."""
    return [e async for e in gen]

async def test_streaming():
    events = await collect_all(llm_handler({"query": "hello"}))

    # Verify FLY events
    fly_events = [e for e in events if isinstance(e, tuple) and e[0] == "FLY"]
    assert len(fly_events) > 0
    assert all(e[1].get("partial") is True for e in fly_events)
    assert all("text" in e[1] for e in fly_events)

    # Verify final payload
    payloads = [e for e in events if isinstance(e, dict)]
    assert payloads[-1]["response"] is not None
```

---

## Performance considerations

- FLY events are **not queued** — they're delivered synchronously via HTTP from the sidecar to the gateway
- High-frequency FLY (e.g., per-character token streaming) may add latency to each handler iteration
- For extremely high-frequency updates (>100/sec), consider batching or sampling

**Best practice**: Stream tokens as they arrive (natural LLM cadence), but avoid yielding FLY in tight CPU-bound loops.

---

## See also

| Topic | Document |
|-------|----------|
| **Streaming events reference** (all event types, protocol mapping) | [docs/reference/specs/streaming-events.md](../reference/specs/streaming-events.md) |
| ABI protocol reference | [docs/reference/specs/abi-protocol.md](../reference/specs/abi-protocol.md) |
| Gateway SSE endpoints | [docs/reference/components/core-gateway.md](../reference/components/core-gateway.md) |
| Agentic patterns (pause/resume, history) | [docs/usage/guide-agentic-patterns.md](guide-agentic-patterns.md) |
| Testing handlers locally | [docs/reference/specs/abi-protocol.md](../reference/specs/abi-protocol.md#testing-handlers-locally) |
