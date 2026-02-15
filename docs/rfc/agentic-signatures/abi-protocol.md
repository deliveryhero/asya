# Asya Actor Yield ABI

## 1. Scope and purpose

This ABI defines the **in-band control interface** between:

* **Actor handlers** (user code)
* **Actor runtime** (scheduler / router / sidecar bridge)

The ABI enables:

* bidirectional metadata access
* deterministic suspension points
* composable actor logic
* streaming and fan-out semantics

The ABI is **generator-based** and **single-stack**, designed to operate within Python’s async execution model without callbacks, threads, or side channels.

---

## 2. Execution model

### 2.1 Actor kinds

An actor handler MAY be one of:

1. **Coroutine actor**

   ```python
   async def actor(payload) -> dict | None
   ```

2. **Async generator actor**

   ```python
   async def actor(payload):
       yield dict
       ...
   ```

3. **Async generator actor using the ABI**

   ```python
   async def actor(payload):
       route = yield ".route"
       yield ".route", route
       yield payload
   ```

The ABI applies **only** to async generator actors.

---

### 2.2 Single-driver rule (normative)

> An actor generator MUST be driven exclusively by the runtime via
> `__anext__()` and `asend()`.

Actors MUST NOT:

* call `asend()` themselves
* store generator references
* interact with the event loop directly

---

## 3. Yield instruction space

Every `yield` from an ABI-aware actor MUST produce exactly one of the following:

### 3.1 PAYLOAD frame

```python
yield <dict>
```

**Meaning**

* Emit a downstream message
* Snapshot current runtime metadata (message) into the frame

**Runtime behavior**

* Clone route and headers
* Deliver frame to sidecar
* Resume actor with `None`

---

### 3.2 GET command

```python
value = yield ".<field>"
```

**Fields**

* `.route`
* `.headers`
* `.id`

**Meaning**

* Actor requests read access to runtime metadata (message)

**Runtime behavior**

* Suspend actor
* Resume via `asend(value)` where `value` is a deep copy
* No metadata mutation occurs

---

### 3.3 SET command

```python
yield (".<field>", value)
```

**Fields**

* `.route`
* `.headers`

**Meaning**

* Actor requests metadata mutation

**Runtime behavior**

* Validate value
* Replace runtime state with deep copy
* Resume actor with `None`

---

### 3.4 NOOP yield

```python
yield
```

**Meaning**

* Explicit suspension point
* No side effects
* Used for control transfer or scoping

**Runtime behavior**

* Resume immediately with `None`

---

## 4. Control-flow semantics

### 4.1 Suspension contract

* Every `yield` is a **hard suspension boundary**
* The runtime determines when execution resumes
* Actors MUST assume metadata may change between yields

---

### 4.2 Determinism guarantee

Given:

* identical payload
* identical initial route and headers
* identical runtime

Then:

> The observable sequence of yields and emitted frames MUST be deterministic.

---

## 5. Scoping and delegation

### 5.1 Yield delegation (ABI-compliant)

Actors MAY delegate ABI operations using generator delegation:

```python
yield from helper()
```

Rules:

* The delegated generator MUST obey the same ABI
* The runtime MUST treat delegated yields identically
* Delegation MUST be transparent to the runtime

This enables:

* macros
* protocol helpers
* structured route mutations

---

### 5.2 Forbidden abstractions (normative)

Actors MUST NOT:

* use `await` to perform ABI operations
* use `asynccontextmanager` for ABI interaction
* communicate metadata via globals, queues, or futures

Rationale:

> These abstractions break suspension symmetry and runtime control.

---

## 6. Lifetime and termination

### 6.1 Normal termination

* Actor completes via `StopAsyncIteration`
* Runtime stops driving the generator
* No implicit cleanup is performed

---

### 6.2 Abort semantics

For coroutine actors:

```python
return None
```

For generator actors:

```python
return
```

Meaning:

* Abort execution
* Emit no further frames

---

## 7. Error handling

### 7.1 Actor errors

If an actor raises an exception:

* Runtime MUST terminate execution
* Runtime MAY emit diagnostics
* Partial frames MAY already have been emitted

---

### 7.2 Protocol violations

If an actor yields an invalid value:

* Runtime MUST raise a protocol error
* Execution MUST terminate immediately

---

## 8. ABI invariants (summary)

1. **Single stack** — no reentrancy
2. **Runtime-driven** — actor never resumes itself
3. **Yield-only ABI** — no side channels
4. **Composable** — `yield from` is first-class
5. **Deterministic** — no hidden state

---

## 9. Design rationale (non-normative)

This ABI intentionally:

* treats `yield` as a syscall instruction
* avoids ambient mutable state
* preserves linear, readable actor code
* aligns with Python’s execution model

The ABI cannot be implemented using:

* `await`
* futures
* callbacks
* context managers

without losing correctness or composability.

---

## 10. Reference mental model

Think of an actor as a **userland process** and the runtime as a **kernel**.

| Concept             | ABI analogue          |
| ------------------- | --------------------- |
| `yield ".route"`    | `sys_read(ROUTE)`     |
| `yield ".route", v` | `sys_write(ROUTE, v)` |
| `yield dict`        | `send_frame()`        |
| `yield from`        | inlined syscall macro |

---

If you want, next we can:

* lock this into a formal RFC doc
* define a typed opcode enum version
* specify a “pure actor” subset (no SET)
* or design static analyzers that validate ABI usage

You’ve already done the hard part—the ABI just needed a name and a spine.
