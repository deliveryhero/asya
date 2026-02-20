---
title: "Epic: Handler Signature Redesign"
status: open
priority: 2 # medium
type: epic
---

Redesign Asya's handler signatures to support typed parameters, output key naming, local variable serialization, and framework-compatible tool definitions. Message metadata access via a virtual filesystem at `/tmp/msg/`.

## Vision

Move beyond the current dict-only handler signatures to support:
1. Typed parameters: `def get_weather(city: str) -> str`
2. Output key naming: where does the result go in the payload?
3. TypedDict/Pydantic payloads: compile-time checking, schema generation
4. Framework decorator detection: @tool from ADK, LangChain, etc.
5. Magic parameter injection: context, stream_writer, tool_context (auto-excluded from schema)
6. Local variable serialization: auto-save/restore across await boundaries
7. **Message metadata as virtual filesystem**: `/tmp/msg/` for route/header access

## Current State
- payload mode: `def handler(p: dict) -> dict` — single dict in, single dict out
- envelope mode: `def handler(e: dict) -> dict` — full envelope access
- No typed params, no output key, no async, no streaming

## Key RFCs
- .aim/aims/1cnt.epic-agent-flow-compi/README.md (CPS transformation, async/await)
- .aim/aims/1dmf.ready-stateful-actors/README.md (transparent filesystem emulation for persistent state — same `open()` interception pattern)
- .aim/aims/1fbe.redesign-protocol-sidecar-runtime/README.md (HTTP over Unix socket protocol — replaces current binary framing)
- docs/rfc/agentic-signatures/survey-agentic-frameworks.md (14-framework survey)

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
- **No asya pip package** — handler signatures must be pure Python
- **No context object injection** — handlers must not have asya-specific parameters
- **File-based metadata access** — follows Linux `/proc` philosophy

---

## RFC: Handler Contract Redesign

This RFC defines the contract between **user handler code** and **asya_runtime.py**, including the message schema, handler signatures, and metadata access via the `/tmp/msg/` virtual filesystem.

### Design rationale for `/tmp/msg/`

**Design constraints**:
1. Handler signatures must be **pure working Python** — no asya imports, no magic parameters
2. Mechanism must be **"foreign" enough** not to look like business logic
3. Must be **"innocent"** — work with real entities when run/tested locally
4. Must work **without an asya pip package**

The `/tmp/msg/` virtual filesystem satisfies all four: handlers read/write plain files, which work with real directories locally and are intercepted by the runtime when deployed. This follows the Linux `/proc` philosophy — `/proc` reflects process state as a filesystem, `/tmp/msg/` reflects message state as a filesystem.

**Related design**: The [stateful actors RFC](.aim/aims/1dmf.ready-stateful-actors/README.md) uses the same `open()` interception pattern for persistent state at `/state/...` paths. The runtime's patched `open()` becomes a path-prefix router:

| Path prefix | Backend (deployed) | Backend (local) | Lifecycle |
|---|---|---|---|
| `/state/meta/...` | State proxy sidecar → Redis | Real files | Persistent across messages |
| `/state/media/...` | State proxy sidecar → S3 | Real files | Persistent across messages |
| `/tmp/msg/...` | In-memory message object | Real files | Fresh per handler invocation |
| Other paths | Real filesystem | Real filesystem | — |

---

### 1. Message schema

#### 1.1 Route schema

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

---

### 2. `/tmp/msg/` virtual filesystem

Message metadata is exposed as a virtual filesystem at `/tmp/msg/` (configurable via `ASYA_MSG_ROOT` env var). Handlers access it via standard Python `open()`.

#### 2.1 Filesystem layout

```
/tmp/msg/                          # per-invocation, like /proc/self/
├── id                             # read-only: msg-uuid-001
├── parent_id                      # read-only: msg-uuid-000
├── route/
│   ├── prev                       # read-only: actor_a\nactor_b
│   ├── curr                       # read-only: analyzer
│   └── next                       # read-write: postprocessor
└── headers/
    ├── trace_id                   # read-write: trace-abc-123
    └── priority                   # read-write: high
```

#### 2.2 File formats

**Plain text, no JSON.** Values follow the simplest format for each type:

| Path | Type | Format | Example content |
|---|---|---|---|
| `/tmp/msg/id` | scalar | raw UTF-8 | `msg-uuid-001` |
| `/tmp/msg/parent_id` | scalar | raw UTF-8 | `msg-uuid-000` |
| `/tmp/msg/route/prev` | list | one per line | `actor_a\nactor_b` |
| `/tmp/msg/route/curr` | scalar | raw UTF-8 | `analyzer` |
| `/tmp/msg/route/next` | list | one per line | `postprocessor` |
| `/tmp/msg/headers/{key}` | scalar | raw UTF-8 | `high` |

**No trailing newlines.** Empty list = empty file (0 bytes).

Reading patterns:
```python
# Scalar
with open("/tmp/msg/id") as f:
    msg_id = f.read()                      # "msg-uuid-001"

# List
with open("/tmp/msg/route/next") as f:
    actors = f.read().splitlines()         # ["postprocessor"]

# Header
with open("/tmp/msg/headers/priority") as f:
    priority = f.read()                    # "high"

# List headers
import os
headers = os.listdir("/tmp/msg/headers/")  # ["trace_id", "priority"]
```

Writing patterns:
```python
# Set route/next
with open("/tmp/msg/route/next", "w") as f:
    f.write("\n".join(["express_handler", "payment"]))

# Set header
with open("/tmp/msg/headers/priority", "w") as f:
    f.write("high")

# Create new header
with open("/tmp/msg/headers/processed_by", "w") as f:
    f.write("enricher-v2")

# Delete header
import os
os.remove("/tmp/msg/headers/internal_debug")
```

#### 2.3 Access control

| Path | read | write | delete | Rationale |
|---|---|---|---|---|
| `/tmp/msg/id` | ✅ | ❌ | ❌ | Immutable message identity |
| `/tmp/msg/parent_id` | ✅ | ❌ | ❌ | Immutable lineage |
| `/tmp/msg/route/prev` | ✅ | ❌ | ❌ | History is append-only by runtime |
| `/tmp/msg/route/curr` | ✅ | ❌ | ❌ | Set by runtime, not handler |
| `/tmp/msg/route/next` | ✅ | ✅ | ✅ | Handler controls future routing |
| `/tmp/msg/headers/` | ✅ | — | — | Directory listing |
| `/tmp/msg/headers/{key}` | ✅ | ✅ | ✅ | Handler can modify routing metadata |

Write to a read-only path raises `PermissionError`. In local development (no interception), no enforcement — same as state proxies having no CAS enforcement locally.

#### 2.4 No `/tmp/msg/payload`

The payload is the function argument and return value. It is NOT accessible via `/tmp/msg/payload`. This avoids two-sources-of-truth confusion (return value vs file content).

#### 2.5 Runtime lifecycle per message

1. Runtime receives message from sidecar via HTTP over Unix socket (see [protocol RFC](.aim/aims/1fbe.redesign-protocol-sidecar-runtime/README.md))
2. Runtime populates `/tmp/msg/` virtual filesystem from message fields
3. Runtime calls handler with `payload` only
4. For generators: at each `yield`, runtime snapshots `/tmp/msg/` state into the emitted frame
5. After handler returns: runtime reads `/tmp/msg/route/next` and `/tmp/msg/headers/` for the final frame
6. Runtime shifts route (`prev.append(curr)`, `curr = next[0]`, `next = next[1:]`)
7. Runtime sends response to sidecar
8. Runtime clears `/tmp/msg/` virtual filesystem

#### 2.6 Implementation

The runtime patches `builtins.open` and routes by path prefix:

```python
def _patched_open(path, mode="r", *args, **kwargs):
    if path.startswith(_msg_root):          # /tmp/msg/...
        return MessageVirtualFile(_current_message, path, mode)
    elif path.startswith(_state_root):      # /state/...
        return StateProxyFile(path, mode)   # Unix socket to sidecar
    else:
        return _original_open(path, mode, *args, **kwargs)
```

The `MessageVirtualFile` is backed by an in-memory dict — no disk I/O, no sidecar, no network. Reads and writes operate directly on the message object.

For `os.listdir`, `os.path.exists`, `os.path.isdir`, `os.remove` — similar patching for `/tmp/msg/` paths.

---

### 3. Handler signatures

All handlers receive **payload only** (not the full message). The handler signature determines how results are returned.

#### 3.1 Sync function (return)

```python
def process(payload):
    return {"result": payload["text"].upper()}
```

- Returns `dict` → one downstream frame
- Returns `None` (or bare `return`) → no frame emitted (abort)
- Simplest form — pure Python, no file I/O needed

#### 3.2 Async function (return)

```python
async def process(payload):
    result = await call_llm(payload["prompt"])
    return {"response": result}
```

- Same semantics as sync, but supports `await` for I/O
- Returns `dict` → one downstream frame
- Returns `None` → abort
- **Recommended** for handlers that call external APIs

#### 3.3 Sync generator (yield)

```python
def process(payload):
    yield {"chunk": "part 1"}
    yield {"chunk": "part 2"}
```

- Each `yield dict` → one downstream frame
- `yield dict, True` → upstream partial frame (for streaming to gateway)
- Generator exhaustion → normal termination
- Bare `return` → abort (no more frames)
- Can read/write `/tmp/msg/` between yields

#### 3.4 Async generator (yield)

```python
async def process(payload):
    async for token in stream_llm(payload["prompt"]):
        yield {"token": token}, True
    yield {"response": full_text}
```

- Same yield semantics as sync generator
- Supports `await` within the generator body
- **Recommended** for LLM streaming handlers

#### 3.5 Class-based handlers

Any of the above signatures can be a method on a class:

```python
class Processor:
    def __init__(self, model_path="/models/default"):
        self.model = load_model(model_path)

    def process(self, payload):
        return {"result": self.model.predict(payload)}
```

- `__init__` is called once at startup (must have default args)
- The method follows the same signature rules as function handlers
- Configure via `ASYA_HANDLER=module.Processor.process`

---

### 4. Yield protocol

Generator handlers communicate with the runtime through `yield`. Yields are **frame emission only** — metadata access goes through `/tmp/msg/` files.

| Yielded value | Type | Instruction |
|---|---|---|
| `{"key": "val"}` | `dict` | EMIT downstream frame |
| `({"key": "val"}, True)` | `(dict, True)` | EMIT upstream partial |
| `({"key": "val"}, False)` | `(dict, False)` | EMIT downstream frame |
| (bare yield) | `None` | NOOP (suspension point) |
| anything else | — | protocol error |

#### Generator driving loop (pseudocode)

```python
gen = handler(payload)
result = next(gen)                              # or __anext__ for async

while True:
    if result is a dict:                        # EMIT downstream
        snapshot_msg_state()                    # capture /tmp/msg/ state
        emit_frame(result, partial=False)
        result = gen.send(None)

    elif result is (dict, True):                # EMIT upstream
        emit_frame(result[0], partial=True)
        result = gen.send(None)

    elif result is None:                        # NOOP
        result = gen.send(None)

    else:
        raise ProtocolError(f"invalid yield: {result!r}")
```

The `snapshot_msg_state()` call captures the current `/tmp/msg/route/next` and `/tmp/msg/headers/` state, attaching it to the emitted frame. This allows different frames from the same generator to have different routes.

---

### 5. Examples

#### 5.1 Simple payload processor (sync, return)

The simplest handler. No `/tmp/msg/` interaction. Pure Python, testable anywhere.

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

#### 5.3 Conditional router (sync, /tmp/msg/ write)

A router that directs messages based on payload content. Writes to `/tmp/msg/route/next`.

```python
def router(payload):
    if payload.get("type") == "express":
        route = ["express_handler", "payment"]
    elif payload.get("type") == "bulk":
        route = ["batch_collector", "bulk_handler", "payment"]
    else:
        route = ["standard_handler", "payment"]

    with open("/tmp/msg/route/next", "w") as f:
        f.write("\n".join(route))

    return payload
```

**Test with real files — no mocks**:

```python
import os

def test_express_routing(tmp_path):
    # Create /tmp/msg/ structure
    route_dir = tmp_path / "msg" / "route"
    route_dir.mkdir(parents=True)
    (route_dir / "next").write_text("postprocessor")

    # Monkeypatch /tmp/msg → tmp_path/msg
    with monkeypatch_msg_root(tmp_path / "msg"):
        result = router({"type": "express"})

    actors = (route_dir / "next").read_text().splitlines()
    assert actors == ["express_handler", "payment"]
    assert result == {"type": "express"}
```

---

#### 5.4 Middleware injector (sync, read + write)

Injects preprocessing steps before the existing planned route.

```python
def middleware(payload):
    if payload.get("needs_validation"):
        with open("/tmp/msg/route/next") as f:
            future = f.read().splitlines()
        with open("/tmp/msg/route/next", "w") as f:
            f.write("\n".join(["validator", "sanitizer"] + future))

    return payload
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

No `/tmp/msg/` access needed — pure streaming, no routing decisions.

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

#### 5.7 Fan-out with different routes (sync, /tmp/msg/ + yield)

Each fan-out frame can have a different route by writing `/tmp/msg/route/next` before each emission.

```python
def smart_splitter(payload):
    for item in payload["items"]:
        if item["priority"] == "high":
            route = ["fast_track", "notify"]
        else:
            route = ["standard_queue"]

        with open("/tmp/msg/route/next", "w") as f:
            f.write("\n".join(route))

        yield {"item": item}
```

Runtime snapshots `/tmp/msg/` state at each `yield`, so each frame gets its own route.

---

#### 5.8 Header manipulation (sync, /tmp/msg/ read/write/delete)

Reading, setting, and deleting headers.

```python
import os

def enrich(payload):
    # Read existing header
    with open("/tmp/msg/headers/trace_id") as f:
        trace_id = f.read()

    # Set new headers
    with open("/tmp/msg/headers/processed_by", "w") as f:
        f.write("enrich-v2")
    with open("/tmp/msg/headers/trace_id", "w") as f:
        f.write(trace_id + "-enriched")

    # Delete a header
    os.remove("/tmp/msg/headers/internal_debug")

    return {"enriched": True, **payload}
```

---

#### 5.9 Class-based handler (async, yield + partial)

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

#### 5.10 Read-only introspection (sync, /tmp/msg/ read)

Handler that reads message metadata for logging/decisions without modifying anything.

```python
import os

def inspector(payload):
    with open("/tmp/msg/id") as f:
        msg_id = f.read()
    with open("/tmp/msg/route/curr") as f:
        curr = f.read()
    with open("/tmp/msg/route/next") as f:
        remaining = f.read().splitlines()

    headers = {}
    for key in os.listdir("/tmp/msg/headers/"):
        with open(f"/tmp/msg/headers/{key}") as f:
            headers[key] = f.read()

    return {
        **payload,
        "meta": {
            "msg_id": msg_id,
            "actor": curr,
            "remaining_steps": len(remaining),
            "trace_id": headers.get("trace_id"),
        },
    }
```

---

#### 5.11 Skip to completion (sync, empty route/next)

Handler that conditionally short-circuits the pipeline.

```python
def gate(payload):
    if not payload.get("approved", False):
        # Empty route/next → x-sink
        with open("/tmp/msg/route/next", "w") as f:
            pass  # write empty file = empty actor list

        return {"status": "rejected", "reason": "not approved"}

    return payload  # continue pipeline
```

---

#### 5.12 Combined routing + streaming (async, full usage)

An advanced handler combining route manipulation, header access, upstream streaming, and downstream emission.

```python
import os

async def orchestrator(payload):
    # Read current route context
    with open("/tmp/msg/route/next") as f:
        current_next = f.read().splitlines()

    with open("/tmp/msg/headers/priority") as f:
        priority = f.read()

    # Set trace header
    with open("/tmp/msg/headers/orchestrator_version", "w") as f:
        f.write("v3")

    # Decide route based on payload + headers
    if priority == "critical":
        route = ["fast_track", "alert", "persist"]
    else:
        route = ["standard_pipeline", "persist"]

    with open("/tmp/msg/route/next", "w") as f:
        f.write("\n".join(route))

    # Stream progress upstream
    yield {"status": "routing_decided", "path": route}, True

    # Process and emit downstream
    result = await heavy_computation(payload)
    yield {"result": result}
```

---

#### 5.13 Retry-after header override

When an LLM API returns 429 with Retry-After, the handler writes a custom header before re-raising:

```python
async def handler(payload):
    try:
        result = await llm.call(payload)
        return {"result": result}
    except RateLimitError as e:
        with open("/tmp/msg/headers/_error_retry_after_ms", "w") as f:
            f.write(str(int(e.retry_after * 1000)))
        raise  # re-raise so runtime treats it as error → x-sump
```

The `x-sump` crew actor checks for `_error_retry_after_ms` in headers and uses `max(computed_backoff, retry_after_ms)` as the delay.

---

### 6. Migration from payload/envelope modes

This contract replaces `ASYA_HANDLER_MODE=payload|envelope`.

#### 6.1 Payload mode handlers (no changes needed)

```python
# Before (payload mode)
def process(payload):
    return {"result": payload["text"].upper()}

# After (same — return-based handlers are unchanged)
def process(payload):
    return {"result": payload["text"].upper()}
```

#### 6.2 Envelope mode handlers (migrate to /tmp/msg/)

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

# After (/tmp/msg/ filesystem)
def router(payload):
    with open("/tmp/msg/route/next", "w") as f:
        f.write("\n".join(["a", "b"]))
    return payload
```

#### 6.3 Summary of changes

| Aspect            | Before (envelope mode)                      | After (/tmp/msg/)                     |
| ----------------- | ------------------------------------------- | ------------------------------------- |
| Mode selection    | `ASYA_HANDLER_MODE=payload\|envelope`       | Removed (always payload)              |
| Handler input     | payload or full envelope                    | Always `payload`                      |
| Route access      | Direct dict manipulation                    | `open("/tmp/msg/route/next")`         |
| Header access     | Direct dict manipulation                    | `open("/tmp/msg/headers/{key}")`      |
| Route schema      | `{"actors": [...], "current": int}`         | `{"prev": [...], "curr": str, "next": [...]}` |
| Streaming         | Generator yields dicts                      | `yield dict` / `yield dict, True`     |
| Route validation  | Complex: check `actors[0:current+1]`        | Simple: `prev`/`curr` are read-only files |
| Metadata access   | Direct dict manipulation                    | Standard `open()`/`os.remove()`       |
| Testing           | Direct dict assertions                      | Real files, zero mocks                |
| Dependencies      | None                                        | None (standard library only)          |

---

### 7. Configuration

| Variable | Default | Description |
|---|---|---|
| `ASYA_MSG_ROOT` | `/tmp/msg` | Root path for message virtual filesystem |

When `ASYA_MSG_ROOT` is unset or set to default, the runtime intercepts `open()` calls to `/tmp/msg/...` paths. For local development, handlers work against real files at that path.

---
_Migrated from beads `asya-0gsw`_
