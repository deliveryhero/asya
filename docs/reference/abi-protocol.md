# ABI Protocol Reference

## What is the ABI?

The ABI (Actor Binary Interface) is the yield-based control protocol between
actor handlers and the Asya runtime. It lets your handler code — plain Python
functions — communicate with the platform without importing anything from Asya.

```python
# No imports. No pip packages. Just Python.
async def my_handler(payload):
    prev = yield "GET", ".route.prev"
    yield "SET", ".route.next", ["next_actor"]
    yield "FLY", {"token": "streaming..."}
    yield payload
```

Four verbs: **GET**, **SET**, **DEL**, **FLY**. That's the entire API.

---

## Why the ABI exists

### The platform-not-framework principle

Most AI frameworks require you to install their SDK, inherit from their base
classes, and call their APIs. Your code becomes coupled to the framework.

Asya takes a different approach: **your code is just Python functions**. You
write a handler, deploy it as an actor, and the platform runs it. There are no
`pip install asya` dependencies. No base classes. No decorators from our
library.

But actors sometimes need to do more than transform payloads — they need to:

- **Read envelope metadata** (where did this envelope come from?)
- **Modify routing** (send the result to a different actor than planned)
- **Stream tokens upstream** (deliver LLM output to the gateway in real-time)
- **Set headers** (attach trace IDs, priorities, or custom metadata)

The ABI solves this without introducing dependencies. Your handler `yield`s
tuples, and the runtime interprets them as commands. The mechanism is Python's
own generator protocol — no library, no framework, no import.

### How it works

When you write a generator handler (a function with `yield`), the runtime
**drives** your generator: it calls `send()` / `asend()` on each yield,
dispatches the command, and resumes your code with the result.

```
Actor handler                    Runtime
─────────────                    ───────
yield "GET", ".route.prev"  ──→  resolves path, reads value
                            ←──  send(["actor_a", "actor_b"])
prev = ...                       (handler receives the value)

yield "SET", ".route.next", ["x"]  ──→  validates access, writes value
                                   ←──  send(None)

yield {"result": "done"}    ──→  captures as downstream frame
                            ←──  send(None)
```

Think of each `yield` as a **syscall**: your actor is a userland process,
the runtime is the kernel. The actor suspends, the runtime handles the
request, the actor resumes.

---

## Handler types

Not all handlers need the ABI. Choose the simplest type that fits:

### Function handlers (no ABI)

Return-based handlers that transform payloads. No metadata access.

```python
async def process(payload):
    payload["result"] = await llm.complete(payload["prompt"])
    return payload
```

### Generator handlers (with ABI)

Yield-based handlers that can access metadata, modify routing, stream
tokens, and emit multiple frames.

```python
async def process(payload):
    # Read metadata
    trace_id = yield "GET", ".headers.trace_id"

    # Stream tokens upstream
    async for token in llm.stream(payload["prompt"]):
        yield "FLY", {"type": "text_delta", "token": token}

    # Modify routing
    if payload.get("needs_review"):
        yield "SET", ".route.next", ["reviewer", "notifier"]

    # Emit result downstream
    payload["result"] = await llm.complete(payload["prompt"])
    yield payload
```

**Rule**: if you need metadata access, streaming, or routing control, use a
generator. Otherwise, use a plain function.

---

## Verb reference

### GET — read metadata

```python
value = yield "GET", "<path>"
```

Read a field from the envelope metadata. Returns a **deep copy** — mutating
the returned value does not affect the envelope.

```python
prev = yield "GET", ".route.prev"       # list of previous actors
curr = yield "GET", ".route.curr"       # current actor name
nxt  = yield "GET", ".route.next"       # list of upcoming actors
hdrs = yield "GET", ".headers"          # all headers
tid  = yield "GET", ".headers.trace_id" # single header
mid  = yield "GET", ".id"              # message ID
```

### SET — write metadata

```python
yield "SET", "<path>", <value>
```

Write a value to a writable metadata field. The value is **deep copied**
into the envelope.

```python
# Replace the entire route.next
yield "SET", ".route.next", ["actor_a", "actor_b"]

# Prepend to route.next (insert before existing actors)
yield "SET", ".route.next[:0]", ["urgent_handler"]

# Append to route.next (two options)
# Option 1: read-modify-write
nxt = yield "GET", ".route.next"
yield "SET", ".route.next", nxt + ["final_step"]

# Option 2: slice with a large index (Python slices handle out-of-bounds)
yield "SET", ".route.next[999:]", ["final_step"]

# Set a header
yield "SET", ".headers.trace_id", "abc-123"

# Set status
yield "SET", ".status.phase", "processing"
```

### DEL — remove metadata

```python
yield "DEL", "<path>"
```

Remove a field from the envelope metadata.

```python
yield "DEL", ".headers.trace_id"
yield "DEL", ".route.next"
```

### FLY — stream upstream

```python
yield "FLY", <dict>
```

Emit a streaming frame **upstream** to the gateway. FLY frames bypass message
queues — they're delivered directly via SSE to connected clients. Use this for
real-time LLM token streaming.

```python
async def llm_handler(payload):
    async for token in model.stream(payload["query"]):
        yield "FLY", {"type": "text_delta", "token": token}

    payload["response"] = await model.complete(payload["query"])
    yield payload
```

FLY frames are **fire-and-forget**: the runtime delivers them to the sidecar,
which forwards them to the gateway. They are not routed through message queues
and not persisted.

### EMIT — send downstream

```python
yield <dict>
```

Emit a payload dict as a downstream frame. The runtime wraps it with the
current route and headers and delivers it to the sidecar for routing to the
next actor.

```python
yield {"result": "processed data"}
```

A generator can emit **multiple frames** — each yield of a dict produces a
separate downstream envelope (fan-out):

```python
async def splitter(payload):
    for item in payload["items"]:
        yield "SET", ".route.next", ["item_processor"]
        yield {"item": item}
```

---

## Path syntax

Paths use **jq-like dot notation** rooted at the envelope envelope.

### Dot access

```
.route.next       → envelope["route"]["next"]
.headers.trace_id → envelope["headers"]["trace_id"]
.route            → envelope["route"]  (entire subtree)
```

The leading `.` is required and refers to the envelope root.

### Bracket access

For keys containing dots or special characters:

```python
yield "GET", '.headers["model.config.version"]'
```

Dot and bracket notation mix freely:

```python
yield "GET", '.status["error.detail"].message'
```

### Index access

```python
yield "GET", ".route.next[0]"    # first element
yield "GET", ".route.next[-1]"   # last element
```

### Slice access (SET only)

Slices work only in SET commands on list fields:

```python
yield "SET", ".route.next[:0]", ["prepend"]    # insert at beginning
yield "SET", ".route.next[1:3]", ["replace"]   # replace range
yield "SET", ".route.next[999:]", ["append"]   # append (large index trick)
```

---

## Access control

Not all metadata fields are writable. The ABI enforces access control:

| Path prefix    | GET  | SET   | DEL   |
|----------------|------|-------|-------|
| `.id`          | read | deny  | deny  |
| `.parent_id`   | read | deny  | deny  |
| `.route.prev`  | read | deny  | deny  |
| `.route.curr`  | read | deny  | deny  |
| `.route.next`  | read | write | write |
| `.headers.*`   | read | write | write |
| `.status`      | read | write | deny  |

The envelope **payload** is not accessible via the ABI — it's the function
argument itself. The ABI operates on envelope metadata only.

---

## Type-based dispatch

The runtime dispatches on the Python type of the yielded value:

| Yielded value | Type | Instruction |
|---|---|---|
| `{"key": "val"}` | `dict` | EMIT downstream |
| `("FLY", {"token": "..."})` | `(str, dict)` | FLY upstream |
| `("GET", ".route.prev")` | `(str, str)` | GET |
| `("SET", ".route.next", [...])` | `(str, str, any)` | SET |
| `("DEL", ".headers.x")` | `(str, str)` | DEL |
| bare `yield` | `None` | no-op |

Anything else is a **protocol error** and terminates execution.

The key insight: `dict` = data (downstream payload), `tuple` = control
(ABI command). The runtime never inspects the contents of dict payloads.
This clean separation means you can put anything in your payload without
conflicting with control signals.

---

## Delegation and composition

### Sync generators: `yield from`

Extract reusable ABI logic into helper generators:

```python
def set_routing(*actors):
    yield "SET", ".route.next", list(actors)

def my_handler(payload):
    yield from set_routing("actor_a", "actor_b")
    yield payload
```

`yield from` is transparent to the runtime — delegated yields are dispatched
identically to direct yields.

### Async generators: explicit iteration

Async generators don't support `yield from`. Use explicit iteration:

```python
async def set_routing(*actors):
    yield "SET", ".route.next", list(actors)

async def my_handler(payload):
    async for instruction in set_routing("actor_a", "actor_b"):
        yield instruction
    yield payload
```

---

## Testing handlers locally

The ABI's design — no imports, no dependencies — means you can test your
handlers as ordinary Python async generators without any Asya infrastructure.

### The `actor()` wrapper pattern

The simplest approach: consume the generator, filter out ABI tuples (control
events), and return the emitted payload:

```python
async def actor(gen):
    """Drive a generator handler, ignoring ABI control events."""
    events = [e async for e in gen if not isinstance(e, tuple)]
    if len(events) != 1:
        raise ValueError(f"Expected 1 emitted frame, got {len(events)}")
    return events[0]
```

Now test your handlers as plain async functions:

```python
async def test_pipeline():
    state = {"prompt": "hello"}
    state = await actor(llm_handler(state))
    state = await actor(validator(state))
    assert state["valid"] is True
```

The `actor()` wrapper turns a generator handler into an awaitable. ABI
commands (`yield "SET", ...`, `yield "FLY", ...`) are silently filtered —
they're tuples, not dicts. Only the emitted payload passes through.

### As a decorator

For cleaner test code, wrap `actor()` as a decorator:

```python
import functools

def actor(func):
    """Decorator: turn a generator handler into an awaitable for single-payload handlers."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        gen = func(*args, **kwargs)
        events = [e async for e in gen if not isinstance(e, tuple)]
        if len(events) > 1:
            raise ValueError(f"Expected 1 emitted frame for @actor, got {len(events)}")
        return events[0] if events else None
    return wrapper

@actor
async def llm_handler(payload):
    yield "FLY", {"token": "thinking..."}
    payload["result"] = "answer"
    yield payload

# In tests:
async def test_llm():
    result = await llm_handler({"prompt": "hello"})
    assert result["result"] == "answer"
```

### Testing ABI control events

When you need to verify that routing or headers are set correctly, collect
all yields:

```python
async def collect_all(gen):
    """Collect all yields: both ABI commands and emitted frames."""
    return [e async for e in gen]

async def test_routing():
    events = await collect_all(my_handler({"needs_review": True}))

    # Verify ABI commands
    assert ("SET", ".route.next", ["reviewer", "notifier"]) in events

    # Verify emitted payload
    payloads = [e for e in events if isinstance(e, dict)]
    assert len(payloads) == 1
```

### Testing FLY streaming

Verify that your handler streams the right tokens:

```python
async def test_streaming():
    events = await collect_all(llm_handler({"query": "hello"}))

    fly_events = [e for e in events if isinstance(e, tuple) and e[0] == "FLY"]
    assert len(fly_events) > 0
    assert all(isinstance(e[1], dict) for e in fly_events)

    # The last event should be the downstream payload
    payloads = [e for e in events if isinstance(e, dict)]
    assert payloads[-1]["response"] is not None
```

### Testing in a flow

Compose tested handlers into a flow — each `await actor(handler(state))`
simulates a message hop through the Asya actor mesh:

```python
async def test_full_flow():
    state = {"text": "analyze this"}
    state = await actor(preprocessor(state))
    state = await actor(classifier(state))

    if state["category"] == "urgent":
        state = await actor(escalator(state))

    state = await actor(notifier(state))
    assert state["notified"] is True
```

This mirrors the actual Asya execution: each `await` represents a envelope
passing through a queue to the next actor. The difference is that in
production, each actor runs in its own pod; in tests, they run sequentially
in one process.

---

## Design rationale

### Why `yield` and not a library API?

An alternative design would provide an `asya` module:

```python
import asya  # hypothetical

async def handler(payload):
    route = asya.get_route()
    asya.set_route_next(["a", "b"])
    await asya.fly({"token": "..."})
    return payload
```

This is what most frameworks do. But it creates coupling:

- Your handler requires `pip install asya` to run
- Testing requires mocking the `asya` module
- The runtime must manage global state for concurrent handlers
- Your handler can't run outside the Asya ecosystem

With the yield-based ABI:

- Your handler is a plain Python generator — no imports
- Testing is trivial: iterate the generator and inspect yields
- No global state: the runtime drives each generator independently
- Your handler works anywhere Python runs

### Why tuples for commands?

The ABI separates **control plane** (tuples) from **data plane** (dicts).
The runtime dispatches on `type(yielded_value)` — it never inspects dict
contents for control signals. This means:

- You can put any key in your payload, including `"type"`, `"command"`,
  `"action"` — nothing collides with ABI commands
- The runtime is a pure instruction dispatcher, not a payload parser
- Protocol errors are caught immediately by type checking

### Why FLY instead of `partial: True`?

An earlier design mixed control signals with payload data:

```python
# Old approach: runtime had to inspect every dict for "partial" key
yield {"partial": True, "token": "hello"}
```

FLY makes the signal structural (tuple type) not semantic (dict key):

```python
# New approach: type dispatch, no dict inspection
yield "FLY", {"token": "hello"}
```

---

## Quick reference

```python
# ── Read metadata ───────────────────────────────
value = yield "GET", ".path.to.field"

# ── Write metadata ──────────────────────────────
yield "SET", ".route.next", ["actor_a", "actor_b"]
yield "SET", ".route.next[:0]", ["prepend"]
yield "SET", ".headers.trace_id", "abc-123"

# ── Delete metadata ─────────────────────────────
yield "DEL", ".headers.trace_id"

# ── Stream upstream (SSE to gateway) ────────────
yield "FLY", {"type": "text_delta", "token": "..."}

# ── Emit downstream (to next actor) ─────────────
yield payload

# ── Delegation ──────────────────────────────────
yield from helper()           # sync generators
async for cmd in helper():   # async generators
    yield cmd
```

---

## Further reading

- [Flow DSL Reference](flow-dsl.md) — compile Python control flow into
  router actor networks (routers use the ABI internally)
- [Architecture: Actor Envelope Protocol](../architecture/protocols/actor-actor.md) —
  envelope envelope format and routing semantics
