# Asya Actor Yield ABI

## 1. Scope and purpose

This ABI defines the **in-band control interface** between:

* **Actor handlers** (user code — sync or async generators)
* **Actor runtime** (`asya_runtime.py` — the driver)

The ABI enables:

* metadata access via four verbs: **GET**, **SET**, **DEL**, **FLY**
* downstream frame emission (routed to next actor)
* upstream streaming emission via FLY (streamed to gateway)
* deterministic suspension points
* composable actor logic via `yield from`

The ABI is **generator-based** and **single-stack**, designed to operate within
Python's sync and async execution models without callbacks, threads, or side
channels.

---

## 2. Execution model

### 2.1 Actor kinds

An actor handler MAY be one of:

1. **Function actor** (sync or async, returns a value)

   ```python
   def actor(payload) -> dict | None
   async def actor(payload) -> dict | None
   ```

2. **Generator actor** (sync or async, yields frames)

   ```python
   def actor(payload):
       yield {"result": "data"}

   async def actor(payload):
       yield {"result": "data"}
   ```

3. **Generator actor using the ABI** (sync or async)

   ```python
   def actor(payload):
       route = yield "GET", ".route"
       yield "SET", ".route.next", ["step_a", "step_b"]
       yield payload
   ```

The ABI applies to **all generator actors**. Function actors (return-based)
do not interact with the ABI.

---

### 2.2 Single-driver rule (normative)

> A generator actor MUST be driven exclusively by the runtime via
> `send()` / `asend()` and `__next__()` / `__anext__()`.

Actors MUST NOT:

* call `send()` / `asend()` on themselves
* store generator references
* interact with the event loop directly

---

## 3. Yield instruction space

Every `yield` from a generator actor MUST produce exactly one of the following
instructions. The runtime dispatches on the **Python type** of the yielded value.

### 3.1 EMIT frame (downstream)

```python
yield <dict>
```

**Meaning**: Emit a routed message to the next actor in `.route.next`.

**Runtime behavior**:

* Snapshot current route and headers into the frame
* Deliver frame to sidecar for downstream routing
* Resume actor with `None`

---

### 3.2 FLY (upstream streaming)

```python
yield "FLY", <dict>
```

**Meaning**: Emit a streaming frame upstream to the gateway for live SSE delivery.

**Runtime behavior**:

* Deliver `<dict>` payload to sidecar as an upstream SSE event
* Frame is NOT routed downstream — it bypasses message queues entirely
* Resume actor with `None`

**Example**:

```python
async def llm_handler(payload):
    async for token in model.stream(payload["query"]):
        yield "FLY", {"type": "text_delta", "token": token}
    payload["response"] = await model.complete(payload["query"])
    yield payload
```

The runtime emits each FLY as `event: upstream` in the SSE stream to sidecar.
The sidecar forwards it to the gateway. The gateway broadcasts it as
`event: stream` to SSE clients.

---

### 3.3 GET command

```python
value = yield "GET", "<path>"
```

**Meaning**: Actor requests read access to a message field.

**Runtime behavior**:

* Suspend actor
* Resolve `<path>` against the message structure (see Section 5)
* Resume via `send(value)` / `asend(value)` where `value` is a **deep copy**
* No message mutation occurs

**Example**:

```python
prev_route = yield "GET", ".route.prev"
headers = yield "GET", ".headers"
status = yield "GET", ".status"
```

---

### 3.4 SET command

```python
yield "SET", "<path>", <value>
```

**Meaning**: Actor requests a field mutation on the message.

**Runtime behavior**:

* Validate path is writable (see access control in Section 6)
* Resolve `<path>` including any slice notation
* Replace or insert value at path with a **deep copy** of the provided value
* Resume actor with `None`

**Example**:

```python
# Replace route.next entirely
yield "SET", ".route.next", ["actor_a", "actor_b"]

# Prepend to route.next (insert at position 0)
yield "SET", ".route.next[:0]", ["urgent_handler"]

# Set a header
yield "SET", ".headers.trace_id", "abc-123"
```

---

### 3.5 DEL command

```python
yield "DEL", "<path>"
```

**Meaning**: Actor requests removal of a message field.

**Runtime behavior**:

* Validate path is writable
* Remove the field at path
* Resume actor with `None`

**Example**:

```python
yield "DEL", ".headers.trace_id"
```

---

### 3.6 NOOP yield

```python
yield
```

**Meaning**: Explicit suspension point with no side effects.

**Runtime behavior**: Resume immediately with `None`.

---

## 4. Type-based dispatch

The runtime dispatches on the Python type of the yielded value:

```
Yielded value                          Type seen by runtime          Instruction
─────────────────────────────────────  ────────────────────────────  ───────────
(bare yield)                           NoneType                      NOOP
{"key": "val"}                         dict                          EMIT downstream
("FLY", {"token": "..."})             (str="FLY", dict)             FLY (upstream)
("GET", ".route.prev")                (str="GET", str)              GET
("SET", ".route.next", [...])         (str="SET", str, any)         SET
("DEL", ".headers.trace_id")          (str="DEL", str)              DEL
```

**Dispatch rules**:

1. `dict` alone → EMIT downstream
2. Tuple where `len >= 2` and first element is `"FLY"` → FLY (upstream streaming)
3. Tuple where `len >= 2` and first element is `"GET"` → GET command
4. Tuple where `len >= 3` and first element is `"SET"` → SET command
5. Tuple where `len >= 2` and first element is `"DEL"` → DEL command
6. `None` (bare yield) → NOOP
7. Anything else → **protocol error**, execution terminates

---

## 5. Path syntax

Paths use **jq-like dot notation** with **bracket notation** for escaping
and **Python-like list slicing**.

### 5.1 Dot access

```
.route.next       → message["route"]["next"]
.headers.trace_id → message["headers"]["trace_id"]
.status           → message["status"]
.route            → message["route"]   (entire subtree)
```

The leading `.` is required and refers to the message root.

Dot notation supports identifiers: letters, digits, underscores, hyphens.
This covers the vast majority of keys including `x-asya-fan-in`,
`trace_id`, `_on_error`.

### 5.2 Bracket key access

For keys containing dots, brackets, or other characters outside the
identifier grammar, use bracket notation (following jq convention):

```python
# Key with dots:
yield "GET", '.headers["model.config.version"]'

# Key with brackets:
yield "GET", '.headers["key[0]"]'

# Equivalent — bracket works for any key:
yield "GET", '.headers["trace_id"]'     # same as .headers.trace_id
```

Dot and bracket notation can be mixed freely in a single path:

```python
yield "GET", '.status["error.detail"].message'
```

### 5.3 Index access

```
.route.next[0]    → message["route"]["next"][0]       (first element)
.route.next[-1]   → message["route"]["next"][-1]      (last element)
.events[2]        → message["events"][2]               (element at index 2)
```

Index access on non-list types is a protocol error.

### 5.4 Slice access (SET only)

Slice syntax is valid only in SET commands and only on list-typed fields:

```python
# Prepend: insert elements at the beginning
yield "SET", ".route.next[:0]", ["first", "second"]
# Equivalent to: route_next[:0] = ["first", "second"]

# Append via slice (alternative to full replacement)
yield "SET", ".route.next[len:]", ["last"]

# Replace a range
yield "SET", ".route.next[1:3]", ["replacement"]
```

Slice syntax on string-typed or non-list fields is a protocol error.

### 5.4 Access control

| Path prefix | GET | SET | DEL |
|-------------|-----|-----|-----|
| `.route.prev` | read | deny | deny |
| `.route.curr` | read | deny | deny |
| `.route.next` | read | write | write |
| `.headers.*` | read | write | write |
| `.status` | read | write | deny |
| `.payload` | deny | deny | deny |

Payload is accessed directly by the handler via the function argument.
The ABI operates on message **metadata** only.

---

## 6. Control-flow semantics

### 6.1 Suspension contract

* Every `yield` is a **hard suspension boundary**
* The runtime determines when execution resumes
* Actors MUST assume metadata may change between yields

---

### 6.2 Determinism guarantee

Given:

* identical payload
* identical initial route and headers
* identical runtime version

Then:

> The observable sequence of yields and emitted frames MUST be deterministic.

---

## 7. Scoping and delegation

### 7.1 Yield delegation (sync generators)

Sync generator actors MAY delegate ABI operations using `yield from`:

```python
def routing_helper():
    yield "SET", ".route.next", ["a", "b"]

def actor(payload):
    yield from routing_helper()
    yield payload
```

Rules:

* The delegated generator MUST obey the same ABI
* The runtime MUST treat delegated yields identically
* Delegation MUST be transparent to the runtime

---

### 7.2 Async generator delegation

Async generators do NOT support `yield from`. Use explicit iteration:

```python
async def routing_helper():
    yield "SET", ".route.next", ["a", "b"]

async def actor(payload):
    async for instruction in routing_helper():
        yield instruction
    yield payload
```

---

### 7.3 Forbidden abstractions (normative)

Actors MUST NOT:

* use `await` to perform ABI operations
* communicate metadata via globals, queues, or futures
* wrap ABI yields inside context managers

Rationale:

> These abstractions break suspension symmetry and runtime control.

---

## 8. Lifetime and termination

### 8.1 Normal termination

* Generator completes via `StopIteration` / `StopAsyncIteration`
* Runtime stops driving the generator
* No implicit cleanup is performed

---

### 8.2 Abort semantics

```python
return       # generator: emit no further frames
return None  # function: emit no frame
```

Meaning:

* Terminate execution
* Emit no further frames
* Frames already emitted are NOT recalled

---

## 9. Error handling

### 9.1 Actor errors

If an actor raises an exception:

* Runtime MUST stop driving the generator
* Runtime MUST report the error to the sidecar
* Streaming frames already emitted via FLY are NOT recalled

---

### 9.2 Protocol violations

If an actor yields a value that does not match any dispatch rule:

* Runtime MUST raise a protocol error
* Execution MUST terminate immediately

---

## 10. ABI invariants (summary)

1. **Single stack** — no reentrancy
2. **Runtime-driven** — actor never resumes itself
3. **Four verbs** — GET, SET, DEL, FLY
4. **Type-dispatched** — yielded Python type determines the instruction
5. **No payload inspection** — runtime never looks inside dict payloads for control signals
6. **Composable** — `yield from` is first-class (sync) or explicit iteration (async)
7. **Deterministic** — no hidden state

---

## 11. Design rationale (non-normative)

This ABI intentionally:

* treats `yield` as a syscall instruction
* uses four verbs: three structural JSON verbs (GET/SET/DEL) + one streaming verb (FLY)
* separates control plane (tuples) from data plane (bare dicts)
* avoids ambient mutable state (no globals, no imports from runtime, no file I/O)
* preserves linear, readable actor code
* works identically in sync and async Python

The ABI cannot be implemented using `await`, futures, callbacks, or context
managers without losing correctness or composability.

### Why FLY instead of `partial: True`

The previous convention mixed control signals with payload data:

```python
# OLD: runtime must inspect every dict for "partial" key
yield {"partial": True, "token": "hello"}
```

FLY makes the control signal structural (tuple type) not semantic (dict key):

```python
# NEW: runtime dispatches on type, never inspects dict contents
yield "FLY", {"token": "hello"}
```

This enables the runtime to be a pure instruction dispatcher — it routes
tuples as commands and dicts as payloads without ever looking inside them.

---

## 12. Reference mental model

Think of an actor as a **userland process** and the runtime as a **kernel**.

| Actor code                                    | Kernel analogue              |
| --------------------------------------------- | ---------------------------- |
| `yield "GET", ".route"`                       | `sys_read(ROUTE)`            |
| `yield "SET", ".route.next", ["a", "b"]`      | `sys_write(ROUTE_NEXT, val)` |
| `yield "SET", ".route.next[:0]", ["x"]`       | `sys_splice(ROUTE_NEXT, val)`|
| `yield "DEL", ".headers.trace_id"`            | `sys_unlink(path)`           |
| `yield {"result": ...}`                       | `send_frame(downstream)`     |
| `yield "FLY", {"token": ...}`                 | `send_frame(upstream)`       |
| `yield from helper()`                         | inlined syscall macro        |
