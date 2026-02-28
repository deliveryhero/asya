# Asya Actor Yield ABI

## 1. Scope and purpose

This ABI defines the **in-band control interface** between:

* **Actor handlers** (user code — sync or async generators)
* **Actor runtime** (`asya_runtime.py` — the driver)

The ABI enables:

* metadata access via three structural verbs: **GET**, **SET**, **DEL**
* downstream frame emission (routed to next actor)
* upstream partial emission (streamed to caller/gateway)
* deterministic suspension points
* composable actor logic via `yield from`

The ABI is **generator-based** and **single-stack**, designed to operate within Python's sync and async execution models without callbacks, threads, or side channels.

See [handler-contract.md](handler-contract.md) for handler signatures, route schema, and user-facing examples.

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
       route = yield "GET", "/route"
       yield "SET", "/route/next", ["step_a", "step_b"]
       yield payload
   ```

The ABI applies to **all generator actors**. Function actors (return-based) do not interact with the ABI.

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

Every `yield` from a generator actor MUST produce exactly one of the following instructions. The runtime dispatches on the **Python type** of the yielded value.

### 3.1 EMIT frame (downstream)

```python
yield <dict>
```

**Meaning**: Emit a routed message to the next actor in `/route/next`.

**Runtime behavior**:

* Snapshot current route and headers into the frame
* Deliver frame to sidecar for downstream routing
* Resume actor with `None`

---

### 3.2 EMIT frame (upstream / partial)

```python
yield <dict>, True
```

**Meaning**: Emit a partial/streaming frame upstream to the caller (gateway SSE).

**Runtime behavior**:

* Deliver frame to sidecar marked as partial
* Frame is NOT routed downstream
* Resume actor with `None`

---

### 3.3 GET command

```python
value = yield "GET", "<path>"
```

**Paths**: Any valid path into the message structure (see [handler-contract.md](handler-contract.md) for path resolution and access control).

**Meaning**: Actor requests read access to a message field.

**Runtime behavior**:

* Suspend actor
* Resume via `send(value)` / `asend(value)` where `value` is a **deep copy**
* No message mutation occurs

---

### 3.4 SET command

```python
yield "SET", "<path>", <value>
```

**Meaning**: Actor requests a field mutation on the message.

**Runtime behavior**:

* Validate path is writable (see access control in [handler-contract.md](handler-contract.md))
* Replace value at path with a **deep copy** of the provided value
* Resume actor with `None`

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
Yielded value              Type seen by runtime       Instruction
─────────────────────────  ─────────────────────────  ───────────
(bare yield)               NoneType                   NOOP
{"key": "val"}             dict                       EMIT downstream
({"key": "val"}, True)     (dict, bool=True)          EMIT upstream
({"key": "val"}, False)    (dict, bool=False)         EMIT downstream
("GET", "/path")           (str="GET", str)           GET
("SET", "/path", val)      (str="SET", str, any)      SET
("DEL", "/path")           (str="DEL", str)           DEL
```

**Dispatch rules**:

1. `dict` alone → EMIT downstream (partial=False)
2. Tuple where first element is `dict` → EMIT, second element is `partial` flag
3. Tuple where first element is `"GET"` → GET command
4. Tuple where first element is `"SET"` → SET command
5. Tuple where first element is `"DEL"` → DEL command
6. `None` (bare yield) → NOOP
7. Anything else → **protocol error**, execution terminates

---

## 5. Control-flow semantics

### 5.1 Suspension contract

* Every `yield` is a **hard suspension boundary**
* The runtime determines when execution resumes
* Actors MUST assume metadata may change between yields

---

### 5.2 Determinism guarantee

Given:

* identical payload
* identical initial route and headers
* identical runtime version

Then:

> The observable sequence of yields and emitted frames MUST be deterministic.

---

## 6. Scoping and delegation

### 6.1 Yield delegation (sync generators)

Sync generator actors MAY delegate ABI operations using `yield from`:

```python
def helper():
    yield "SET", "/route/next", ["a", "b"]

def actor(payload):
    yield from helper()
    yield payload
```

Rules:

* The delegated generator MUST obey the same ABI
* The runtime MUST treat delegated yields identically
* Delegation MUST be transparent to the runtime

---

### 6.2 Async generator delegation

Async generators do NOT support `yield from`. Use explicit iteration:

```python
async def helper():
    yield "SET", "/route/next", ["a", "b"]

async def actor(payload):
    async for instruction in helper():
        yield instruction
    yield payload
```

---

### 6.3 Forbidden abstractions (normative)

Actors MUST NOT:

* use `await` to perform ABI operations
* communicate metadata via globals, queues, or futures
* wrap ABI yields inside context managers

Rationale:

> These abstractions break suspension symmetry and runtime control.

---

## 7. Lifetime and termination

### 7.1 Normal termination

* Generator completes via `StopIteration` / `StopAsyncIteration`
* Runtime stops driving the generator
* No implicit cleanup is performed

---

### 7.2 Abort semantics

```python
return       # generator: emit no further frames
return None  # function: emit no frame
```

Meaning:

* Terminate execution
* Emit no further frames
* Frames already emitted are NOT recalled

---

## 8. Error handling

### 8.1 Actor errors

If an actor raises an exception:

* Runtime MUST stop driving the generator
* Runtime MUST report the error to the sidecar
* Partial frames already emitted are NOT recalled

---

### 8.2 Protocol violations

If an actor yields a value that does not match any dispatch rule:

* Runtime MUST raise a protocol error
* Execution MUST terminate immediately

---

## 9. ABI invariants (summary)

1. **Single stack** — no reentrancy
2. **Runtime-driven** — actor never resumes itself
3. **Three verbs** — GET, SET, DEL (structural operations on JSON nodes)
4. **Type-dispatched** — yielded Python type determines the instruction
5. **Composable** — `yield from` is first-class (sync) or explicit iteration (async)
6. **Deterministic** — no hidden state

---

## 10. Design rationale (non-normative)

This ABI intentionally:

* treats `yield` as a syscall instruction
* uses three structural JSON verbs (GET/SET/DEL) that work on any node type
* avoids ambient mutable state (no globals, no imports from runtime)
* preserves linear, readable actor code
* works identically in sync and async Python

The ABI cannot be implemented using `await`, futures, callbacks, or context managers without losing correctness or composability.

---

## 11. Reference mental model

Think of an actor as a **userland process** and the runtime as a **kernel**.

| Actor code                                  | Kernel analogue              |
| ------------------------------------------- | ---------------------------- |
| `yield "GET", "/route"`                     | `sys_read(ROUTE)`            |
| `yield "SET", "/route/next", ["a", "b"]`    | `sys_write(ROUTE_NEXT, val)` |
| `yield "DEL", "/headers/trace_id"`          | `sys_unlink(path)`           |
| `yield {"result": ...}`                     | `send_frame(downstream)`     |
| `yield {"token": ...}, True`                | `send_frame(upstream)`       |
| `yield from helper()`                       | inlined syscall macro        |
