---
title: "Epic: Handler Signature Redesign"
status: open
priority: 2 # medium
type: epic
---

Redesign Asya's handler signatures to support typed parameters, output key naming, local variable serialization, and framework-compatible tool definitions.

## Vision
Move beyond the current dict-only handler signatures to support:
1. Typed parameters: `def get_weather(city: str) -> str`
2. Output key naming: where does the result go in the payload?
3. TypedDict/Pydantic payloads: compile-time checking, schema generation
4. Framework decorator detection: @tool from ADK, LangChain, etc.
5. Magic parameter injection: context, stream_writer, tool_context (auto-excluded from schema)
6. Local variable serialization: auto-save/restore across await boundaries

## Current State
- payload mode: `def handler(p: dict) -> dict` — single dict in, single dict out
- envelope mode: `def handler(e: dict) -> dict` — full envelope access
- No typed params, no output key, no async, no streaming

## Key RFCs
- docs/rfc/agentic-compiler/agentic-compiler-rfc.md (CPS transformation, async/await)
- docs/rfc/agentic-signatures/asya-handler-signatures.md (typed signatures research)
- docs/rfc/agentic-signatures/asya-handler-syntax-comparisons.md (14-framework survey)

## Champion Framework: Google ADK
ADK is the closest architectural match for Asya. Key patterns to adopt:
- output_key (enrichment into shared state)
- Plain functions as tools (no decorator required)
- tool_context magic parameter injection
- Event-based async generators

## Design Decisions (from RFC discussions)
- Last yield = control event (Option B), emit callback rejected
- Enrichment is custom reducer (payload in -> payload out), not append-only
- Free variables across await boundaries: initially error, later auto-serialize
- LangGraph reducer pattern (Annotated[list, add]) — NOT adopted (confusing, scales poorly)


## RFC: Handler Contract Redesign

This RFC defines the contract between **user handler code** and **asya_runtime.py**, including the message schema, handler signatures, yield protocol, and access control.

Companion document: [abi-protocol.md](abi-protocol.md) (low-level yield dispatch specification).

---

### 1. Message schema

#### 1.1 Route schema (new)

The route is split into three temporal fields:

```json
{
  "route": {
    "prev": ["actor_a", "actor_b"],
    "curr": "actor_c",
    "next": ["actor_d", "actor_e"]
  }
}
```

| Field     | Type       | Meaning                               |
| --------- | ---------- | ------------------------------------- |
| `prev`    | `list[str]`| Actors that have already processed    |
| `curr`    | `str`      | Actor currently processing            |
| `next`    | `list[str]`| Actors remaining after current        |

**Runtime shift**: After the handler finishes, the runtime shifts the route:

```
Before:  prev=["a"],    curr="b",  next=["c", "d"]
After:   prev=["a","b"], curr="c", next=["d"]
```

When `next` is empty after the shift, the sidecar routes to `x-sink` (completion).

#### 1.2 Full message structure

```json
{
  "id": "msg-uuid-001",
  "parent_id": "msg-uuid-000",
  "route": {
    "prev": ["preprocessor"],
    "curr": "analyzer",
    "next": ["postprocessor"]
  },
  "headers": {
    "trace_id": "trace-abc-123",
    "priority": "high"
  },
  "payload": {
    "text": "Hello, world"
  }
}
```

| Field       | Type   | Required | Description                          |
| ----------- | ------ | -------- | ------------------------------------ |
| `id`        | `str`  | yes      | Unique message identifier            |
| `parent_id` | `str`  | no       | Original message ID (fanout)         |
| `route`     | `dict` | yes      | Routing state (prev/curr/next)       |
| `headers`   | `dict` | no       | Routing metadata (trace, priority)   |
| `payload`   | `any`  | yes      | Arbitrary JSON data for the handler  |

#### 1.3 Path resolution

Paths use JSON Pointer syntax (RFC 6901) relative to the message root:

```
/id                    → "msg-uuid-001"
/route                 → {"prev": [...], "curr": "...", "next": [...]}
/route/next            → ["postprocessor"]
/route/prev            → ["preprocessor"]
/route/curr            → "analyzer"
/headers               → {"trace_id": "...", "priority": "high"}
/headers/trace_id      → "trace-abc-123"
/headers/priority      → "high"
/payload               → {"text": "Hello, world"}
```

All paths refer to **real fields** in the message JSON. There are no virtual or computed paths.

---

### 2. Access control

The runtime enforces field-level permissions on SET and DEL operations:

| Path              | GET | SET | DEL | Rationale                              |
| ----------------- | --- | --- | --- | -------------------------------------- |
| `/id`             | ✅  | ❌  | ❌  | Immutable message identity             |
| `/parent_id`      | ✅  | ❌  | ❌  | Immutable lineage                      |
| `/route/prev`     | ✅  | ❌  | ❌  | History is append-only by runtime      |
| `/route/curr`     | ✅  | ❌  | ❌  | Set by runtime, not handler            |
| `/route/next`     | ✅  | ✅  | ✅  | Handler controls future routing        |
| `/headers`        | ✅  | ✅  | ✅  | Handler can modify routing metadata    |
| `/headers/<key>`  | ✅  | ✅  | ✅  | Handler can modify individual headers  |
| `/payload`        | ✅  | ✅  | ❌  | Readable; SET allowed for transforms   |

If a handler attempts SET or DEL on a read-only path, the runtime MUST raise a protocol error.

---

### 3. Handler signatures

All handlers receive **payload only** (not the full message). The handler signature determines how results are returned.

#### 3.1 Sync function (return)

```python
def process(payload):
    return {"result": payload["text"].upper()}
```

* Returns `dict` → one downstream frame
* Returns `None` (or bare `return`) → no frame emitted (abort)
* No ABI interaction possible

---

#### 3.2 Async function (return)

```python
async def process(payload):
    result = await call_llm(payload["prompt"])
    return {"response": result}
```

* Same semantics as sync, but supports `await` for I/O
* Returns `dict` → one downstream frame
* Returns `None` → abort

---

#### 3.3 Sync generator (yield)

```python
def process(payload):
    yield {"chunk": "part 1"}
    yield {"chunk": "part 2"}
```

* Each `yield dict` → one downstream frame
* Supports ABI commands (GET/SET/DEL) between yields
* `yield dict, True` → upstream partial frame
* Generator exhaustion → normal termination
* Bare `return` → abort (no more frames)

---

#### 3.4 Async generator (yield)

```python
async def process(payload):
    async for token in stream_llm(payload["prompt"]):
        yield {"token": token}, True
    yield {"response": full_text}
```

* Same yield semantics as sync generator
* Supports `await` within the generator body
* Each `yield` is an ABI instruction (see dispatch table in [abi-protocol.md](abi-protocol.md))

---

#### 3.5 Class-based handlers

Any of the above signatures can be a method on a class:

```python
class Processor:
    def __init__(self, model_path="/models/default"):
        self.model = load_model(model_path)

    def process(self, payload):
        return {"result": self.model.predict(payload)}
```

* `__init__` is called once at startup (must have default args)
* The method follows the same signature rules as function handlers
* Configure via `ASYA_HANDLER=module.Processor.process`

---

### 4. Yield protocol

Generator handlers (sync and async) communicate with the runtime through `yield`. The yielded value determines the instruction.

#### 4.1 Downstream emission

```python
yield {"result": "processed data"}
```

The dict is wrapped into a message frame with the current route/headers snapshot and delivered to the sidecar for routing to the next actor.

---

#### 4.2 Upstream emission (partial / streaming)

```python
yield {"token": "hel"}, True
yield {"token": "hello"}, True
yield {"response": "hello world"}      # final downstream frame
```

Frames yielded with `True` as the second element are sent upstream to the caller (e.g., gateway SSE stream). They are NOT routed to the next actor.

This enables token-by-token LLM streaming while still sending a complete result downstream.

---

#### 4.3 Metadata access (GET / SET / DEL)

```python
# Read a field (GET returns a deep copy via generator send)
route = yield "GET", "/route"
headers = yield "GET", "/headers"
msg_id = yield "GET", "/id"
priority = yield "GET", "/headers/priority"

# Write a field (fire-and-forget, resumes with None)
yield "SET", "/route/next", ["step_a", "step_b"]
yield "SET", "/headers/priority", "high"

# Delete a field (fire-and-forget, resumes with None)
yield "DEL", "/headers/trace_id"
```

**Three verbs. Real paths only.** GET/SET/DEL are structural JSON operations that work on any node type. See [abi-protocol.md](abi-protocol.md) for the full dispatch specification.

---

### 5. Examples

#### 5.1 Simple payload processor (sync, return)

The simplest handler. No ABI interaction. Pure Python, testable anywhere.

```python
def process(payload):
    text = payload["text"]
    return {"sentiment": analyze_sentiment(text), "length": len(text)}
```

**Test without runtime**:

```python
def test_process():
    result = process({"text": "great product"})
    assert result["sentiment"] == "positive"
```

---

#### 5.2 Simple payload processor (async, return)

Identical contract, supports `await` for external calls.

```python
async def process(payload):
    result = await external_api.analyze(payload["text"])
    return {"analysis": result}
```

---

#### 5.3 Conditional router (sync, yield + SET)

A router that directs messages based on payload content. Uses GET/SET to modify the route.

```python
def router(payload):
    if payload.get("type") == "express":
        yield "SET", "/route/next", ["express_handler", "payment"]
    elif payload.get("type") == "bulk":
        yield "SET", "/route/next", ["batch_collector", "bulk_handler", "payment"]
    else:
        yield "SET", "/route/next", ["standard_handler", "payment"]
    yield payload
```

**Test with a driver harness**:

```python
def test_express_routing():
    gen = router({"type": "express"})
    # First yield: SET command
    instruction = next(gen)
    assert instruction == ("SET", "/route/next", ["express_handler", "payment"])
    # Second yield: payload frame
    frame = gen.send(None)
    assert frame == {"type": "express"}
```

---

#### 5.4 Middleware injector (sync, yield + GET/SET prepend)

Injects preprocessing steps before the existing planned route. Uses GET + list concatenation + SET (two lines for prepend).

```python
def middleware(payload):
    if payload.get("needs_validation"):
        future = yield "GET", "/route/next"
        yield "SET", "/route/next", ["validator", "sanitizer"] + future
    yield payload
```

---

#### 5.5 Streaming LLM handler (async, yield + partial)

Streams tokens upstream to the gateway while sending the complete response downstream.

```python
async def llm_handler(payload):
    prompt = payload["prompt"]
    full_response = ""

    async for token in llm_client.stream(prompt):
        full_response += token
        yield {"token": token}, True              # upstream: stream to caller

    yield {"response": full_response}              # downstream: to next actor
```

---

#### 5.6 Fan-out handler (sync, yield multiple frames)

Emits multiple downstream frames. Each frame is routed independently to the next actor.

```python
def splitter(payload):
    for item in payload["items"]:
        yield {"item": item, "batch_id": payload["batch_id"]}
```

Each yielded dict becomes a separate message with its own copy of the current route and headers.

---

#### 5.7 Fan-out with different routes (sync, yield + SET between emissions)

Each fan-out frame can have a different route by SET-ing `/route/next` before each emission.

```python
def smart_splitter(payload):
    for item in payload["items"]:
        if item["priority"] == "high":
            yield "SET", "/route/next", ["fast_track", "notify"]
        else:
            yield "SET", "/route/next", ["standard_queue"]
        yield {"item": item}
```

---

#### 5.8 Header manipulation (sync, yield + GET/SET/DEL)

Reading, setting, and deleting headers.

```python
def enrich(payload):
    # Read existing header
    trace_id = yield "GET", "/headers/trace_id"

    # Set new headers
    yield "SET", "/headers/processed_by", "enrich-v2"
    yield "SET", "/headers/trace_id", trace_id + "-enriched"

    # Delete a header
    yield "DEL", "/headers/internal_debug"

    yield {"enriched": True, **payload}
```

---

#### 5.9 Class-based stateful handler (async, yield + partial)

Model loaded once at init, used for every message. Streams predictions upstream.

```python
class Predictor:
    def __init__(self, model_path="/models/default"):
        self.model = load_model(model_path)

    async def predict(self, payload):
        # Stream intermediate results upstream
        for step in self.model.predict_steps(payload["input"]):
            yield {"step": step, "progress": step.progress}, True

        # Send final result downstream
        yield {"prediction": step.final_result}
```

---

#### 5.10 Read-only introspection (sync, yield + GET)

Handler that reads message metadata for logging/decisions without modifying anything.

```python
def inspector(payload):
    route = yield "GET", "/route"
    msg_id = yield "GET", "/id"
    headers = yield "GET", "/headers"

    yield {
        "payload": payload,
        "meta": {
            "msg_id": msg_id,
            "actor": route["curr"],
            "remaining_steps": len(route["next"]),
            "trace_id": headers.get("trace_id"),
        },
    }
```

---

#### 5.11 Skip to completion (sync, yield + SET empty next)

Handler that conditionally short-circuits the pipeline.

```python
def gate(payload):
    if not payload.get("approved", False):
        yield "SET", "/route/next", []                 # empty next → x-sink
        yield {"status": "rejected", "reason": "not approved"}
        return                                          # stop generator

    yield payload                                       # continue pipeline
```

---

#### 5.12 Combined routing + streaming (async, full ABI usage)

An advanced handler combining route manipulation, header access, upstream streaming, and downstream emission.

```python
async def orchestrator(payload):
    # Read current route context
    route = yield "GET", "/route"
    headers = yield "GET", "/headers"

    # Set trace header
    yield "SET", "/headers/orchestrator_version", "v3"

    # Decide route based on payload + headers
    if headers.get("priority") == "critical":
        yield "SET", "/route/next", ["fast_track", "alert", "persist"]
    else:
        yield "SET", "/route/next", ["standard_pipeline", "persist"]

    # Stream progress upstream
    yield {"status": "routing_decided", "path": route["next"]}, True

    # Process and emit downstream
    result = await heavy_computation(payload)
    yield {"result": result}
```

---

#### 5.13 Streaming with conditional downstream (async, yield + partial)

An actor that streams partial results upstream, then conditionally decides whether to forward a result downstream. If the generator exhausts without emitting a downstream frame, the pipeline terminates at this actor (sidecar routes to x-sink).

```python
async def conditional_streamer(payload):
    yield {"text": "processing..."}, True      # upstream partial
    yield {"text": "almost done..."}, True     # upstream partial

    if payload.get("forward"):
        payload["processed"] = True
        yield payload                           # downstream: continue pipeline
    # else: generator exhausts → no downstream frame → routes to x-sink
```

---

#### 5.14 Generator composition with enrichment (async, delegation)

An async generator that delegates to a helper generator, enriching each event before re-yielding upstream. Uses explicit iteration since async generators do not support `yield from` (see [abi-protocol.md](abi-protocol.md) section 6.2).

```python
async def enriching_proxy(payload):
    # Consume helper's stream, enrich each event, re-yield upstream
    async for event in stream_processor(payload):
        event["enriched_by"] = "proxy"
        yield event, True                      # upstream: enriched partial

    await notify_completion(payload)
    yield {"status": "complete", **payload}    # downstream
```

The helper generator follows the same ABI:

```python
async def stream_processor(payload):
    async for token in llm_client.stream(payload["prompt"]):
        yield {"token": token}, True           # upstream partial
```

---

#### 5.15 Fan-out with mid-stream reroute (sync, yield + GET/SET between emissions)

An actor that emits a frame on the current route, then modifies the route so all remaining frames are delivered to a different set of actors. Unlike example 5.7 (which sets the route before each individual frame), this pattern sets the route once mid-stream, affecting all subsequent emissions.

```python
def rerouting_fan_out(payload):
    # First frame goes to the current route
    yield {**payload, "batch_index": 0}

    # Read current route and prepend an interceptor
    next_actors = yield "GET", "/route/next"
    yield "SET", "/route/next", ["interceptor"] + next_actors

    # Remaining frames go to the modified route
    yield {**payload, "batch_index": 1}
    yield {**payload, "batch_index": 2}
    yield {**payload, "batch_index": 3}
```

---

### 6. Runtime behavior summary

#### 6.1 Handler invocation

1. Runtime receives message from sidecar via Unix socket
2. Runtime validates message structure
3. Runtime extracts `payload` from message
4. Runtime calls handler with `payload`
5. For generators: runtime drives the generator, processing each yielded instruction
6. After handler completes: runtime shifts the route (`prev.append(curr)`, `curr = next.pop(0)`)
7. Runtime sends all emitted frames to sidecar

#### 6.2 Generator driving loop (pseudocode)

```python
gen = handler(payload)
result = next(gen)                              # or __anext__ for async

while True:
    if result is a dict:                        # EMIT downstream
        emit_frame(result, partial=False)
        result = gen.send(None)

    elif result is (dict, True):                # EMIT upstream
        emit_frame(result[0], partial=True)
        result = gen.send(None)

    elif result is ("GET", path):               # GET
        value = deep_copy(resolve(message, path))
        result = gen.send(value)

    elif result is ("SET", path, value):        # SET
        assert_writable(path)
        set_field(message, path, deep_copy(value))
        result = gen.send(None)

    elif result is ("DEL", path):               # DEL
        assert_writable(path)
        delete_field(message, path)
        result = gen.send(None)

    elif result is None:                        # NOOP
        result = gen.send(None)

    else:
        raise ProtocolError(f"invalid yield: {result!r}")
```

---

### 7. Migration from payload/envelope modes

This contract replaces `ASYA_HANDLER_MODE=payload|envelope`.

#### 7.1 Payload mode handlers (no changes needed)

```python
# Before (payload mode)
def process(payload):
    return {"result": payload["text"].upper()}

# After (same — return-based handlers are unchanged)
def process(payload):
    return {"result": payload["text"].upper()}
```

#### 7.2 Envelope mode handlers (migrate to yield + GET/SET)

```python
# Before (envelope mode)
def router(envelope):
    route = envelope["route"]
    current = route["current"]
    route["actors"] = route["actors"][:current + 1] + ["a", "b"]
    return {
        "payload": envelope["payload"],
        "route": route,
        "headers": envelope.get("headers", {}),
    }

# After (yield protocol with new route schema)
def router(payload):
    yield "SET", "/route/next", ["a", "b"]
    yield payload
```

#### 7.3 Summary of changes

| Aspect            | Before                                      | After                                |
| ----------------- | ------------------------------------------- | ------------------------------------ |
| Mode selection    | `ASYA_HANDLER_MODE=payload\|envelope`       | Removed (always payload)             |
| Handler input     | payload (payload mode) or envelope (envelope mode) | Always `payload`              |
| Route access      | Direct dict manipulation (envelope mode)    | `yield "GET"/"SET", "/route/..."`    |
| Header access     | Direct dict manipulation (envelope mode)    | `yield "GET"/"SET", "/headers/..."`  |
| Route schema      | `{"actors": [...], "current": int}`         | `{"prev": [...], "curr": str, "next": [...]}` |
| Streaming         | Generator yields dicts                      | `yield dict` (downstream) or `yield dict, True` (upstream) |
| Route validation  | Complex: check `actors[0:current+1]` unchanged | Simple: `prev` and `curr` are read-only |


---
## Notes

[Error Handling RFC context] The handler signature redesign must support optional headers access for retry_after override. Example use case: when an LLM API returns 429 with Retry-After header, the handler should be able to signal a custom retry delay:

```python
async def handler(payload: dict, headers: dict):
    try:
        result = await llm.call(payload)
        return {"result": result}
    except RateLimitError as e:
        headers["_error"] = {"retry_after_ms": e.retry_after * 1000}
        raise  # re-raise so runtime treats it as error
```

This connects to the error handling RFC (asya-y4kr): the _error crew actor checks for retry_after_ms in headers and uses max(computed_backoff, retry_after_ms) as the delay. Requires the new handler signature where headers are optionally injectable.


---
_Migrated from beads `asya-0gsw`_
