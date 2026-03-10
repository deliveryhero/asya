# Flow DSL Reference

## What is the Flow DSL?

The Flow DSL is a Python-based language for describing how actors are
connected. You write a function that looks like ordinary sequential Python
code. The compiler transforms it into a network of **router actors** that
steer messages through your pipeline at runtime.

```python
async def review_pipeline(state: dict) -> dict:
    state = await classify(state)

    if state["category"] == "urgent":
        state = await escalate(state)
    else:
        state = await standard_review(state)

    state = await notify(state)
    return state
```

This compiles into four router actors that handle sequencing, branching,
and merging. You deploy the routers alongside your handler actors
(`classify`, `escalate`, `standard_review`, `notify`) and Asya runs the
pipeline.

---

## What problem does it solve?

### The router problem

In Asya, every actor receives a message, does its work, and the sidecar
forwards the result to the next actor in `route.next`. Simple chains are
easy — you just list actors in the route:

```json
{"route": {"prev": [], "curr": "classify", "next": ["review", "notify"]}}
```

But the moment you need **branching** (if urgent, escalate; otherwise,
standard review), you need a **router actor** — an actor whose only job is
to inspect the payload and rewrite `route.next`:

```python
def urgency_router(payload):
    if payload["category"] == "urgent":
        yield "SET", ".route.next", ["escalate", "notify"]
    else:
        yield "SET", ".route.next", ["standard-review", "notify"]
    yield payload
```

For a simple if/else this is manageable. But real pipelines have nested
conditions, loops, fan-out, error handling, and early exits. Writing
routers by hand for these is tedious, error-prone, and hard to test in
isolation.

### What Flow solves

Flow automates router generation. You write the control flow once in
readable Python. The compiler produces the router actors. You focus on
business logic in your handler actors.

| You write | Compiler generates |
|---|---|
| `if state["x"]: ...` | Conditional router that rewrites `route.next` |
| `while state["retries"] < 3: ...` | Loop-back router with iteration guard |
| `state = await handler(state)` | Route entry for `handler` in the sequence |
| `try: ... except: ...` | Error dispatch and recovery routers |
| `return state` | End router that signals pipeline completion |

### What Flow does NOT do

Flow is strictly about **control flow** — the order in which actors
execute and the conditions under which they execute. It has no opinion on:

- **Business logic**: what `classify` or `escalate` actually do — that's
  your handler code
- **Data transformation**: how payloads are shaped, validated, or enriched
  — that's inside each actor
- **Streaming**: token-by-token LLM output, SSE events — that's handled
  by the actor's ABI yields (`yield "FLY", {...}`)
- **Data storage**: S3 uploads, database writes — that's your actor's
  concern

Flow groups actors and generates the routing glue between them. Nothing
more.

---

## How Asya executes flows: CPS

### Classic nested execution

In regular Python, function calls form a **call stack**:

```python
def pipeline(data):
    validated = validate(data)       # call, wait, return
    enriched = enrich(validated)     # call, wait, return
    result = process(enriched)       # call, wait, return
    return result
```

Everything runs in one process. State lives on the stack. If `enrich`
raises, Python unwinds the stack through `process` back to `pipeline`.
The caller holds the context — it knows where execution came from and
where it's going next.

### Continuation-Passing Style (CPS)

Asya doesn't have a call stack. Each actor is a separate process (a
Kubernetes pod). There is no caller waiting for a return value. Instead,
the **message itself** carries the continuation — the list of actors that
should run next.

When you write:

```python
async def pipeline(state: dict) -> dict:
    state = await validate(state)
    state = await enrich(state)
    state = await process(state)
    return state
```

This **looks like** sequential function calls, but the compiler transforms
it into something fundamentally different:

```
Message arrives at start_pipeline router
  → router sets route.next = [validate, enrich, process]
  → message sent to validate actor

validate processes payload, returns result
  → sidecar shifts route: curr=enrich, next=[process]
  → message sent to enrich actor

enrich processes payload, returns result
  → sidecar shifts route: curr=process, next=[]
  → message sent to process actor

process processes payload, returns result
  → route is empty → sidecar sends to x-sink (completion)
```

Each `await` compiles to **a message hop between independent actors**, not
a function call within one process. There is no call stack connecting
them. The message's `route` field IS the continuation — it tells the
system what to do next.

### State is in the message

In classic Python, intermediate state lives in local variables, closures,
and the call stack. In Asya, there is exactly one place for state: **the
message payload**.

```python
async def pipeline(state: dict) -> dict:
    state["step"] = "validated"
    state = await validate(state)

    # At this point, we're in a different process.
    # The only thing that survived is what's in state.
    state["step"] = "enriched"
    state = await enrich(state)
    return state
```

When the compiler generates routers, the mutation `state["step"] =
"validated"` becomes part of a router actor that modifies the payload
before forwarding it. The `validate` actor receives the modified payload,
does its work, and the result — with any changes validate made — flows
to the next actor.

**There are no closures, no shared memory, no globals between actors.**

If an actor needs data that isn't in the payload, it reads from external
storage (S3, a database, a cache). The Flow DSL doesn't manage this — it's
the actor's responsibility.

### Why this matters

The CPS model means:

- **Each actor is independently deployable and scalable.** `validate` can
  run on 10 pods while `enrich` runs on 2.

- **Failures are isolated.** If `enrich` crashes, only its message is
  affected. `validate` and `process` are unaware.

- **There is no "pipeline process" to keep alive.** The pipeline is a
  series of queue hops. No long-running orchestrator.

- **Retries are per-actor.** If `process` fails, only that step retries.
  The message (with all accumulated state) re-enters the same actor.

The trade-off: you must be deliberate about what goes into the payload.
Everything the next actor needs must be serialized into the message or
retrievable from external storage.

---

## Writing flows

### Function signature

A flow is a single Python function with a `dict` parameter and `dict`
return type:

```python
async def my_flow(state: dict) -> dict:
    # ... pipeline logic ...
    return state
```

The function can be `def` (sync) or `async def`. Async is recommended —
it matches the mental model of `await` as a message hop.

### Actor calls

Call a handler actor by assigning its result back to the state variable:

```python
state = await validate(state)           # function handler
state = await model.predict(state)      # class method handler
```

Each call compiles to a route entry. The handler function itself is NOT
included in the flow file — it's deployed as a separate actor. The name
in the flow (`validate`) is mapped to an actor name at deployment time
via environment variables.

**Rules:**
- Must pass the state variable as the only argument
- Must assign the result back to the state variable
- Class instantiation must use only default arguments

### Payload mutations

Modify payload fields inline:

```python
state["status"] = "processing"
state["count"] += 1
state["metadata"]["source"] = "api"
```

Mutations compile into router actors that modify the payload before
forwarding. Consecutive mutations are batched into a single router.

### Conditionals

Branch on payload values:

```python
if state["type"] == "express":
    state = await express_handler(state)
elif state["type"] == "bulk":
    state["batch_size"] = 100
    state = await bulk_handler(state)
else:
    state = await standard_handler(state)
```

Each branch compiles to a conditional router that rewrites `route.next`
based on the condition. After the branches rejoin, execution continues
with the next statement.

### Early returns

Exit the flow before the end:

```python
if state.get("skip"):
    return state        # pipeline ends here, message goes to x-sink

state = await process(state)
return state
```

An early `return` compiles to a router that clears `route.next`, causing
the sidecar to route the message to `x-sink` (the terminal actor).

### Loops

Iterate with `while`:

```python
state["attempt"] = 0
while state["attempt"] < 3:
    state["attempt"] += 1
    state = await try_operation(state)
    if state.get("success"):
        break
```

The compiler generates a loop-back router that re-inserts the loop body
actors into `route.next` on each iteration. A guard prevents infinite
loops (configurable via `--max-iterations`, default 100).

`while True:` with `break` is supported for indefinite loops:

```python
while True:
    state = await poll_status(state)
    if state["status"] == "complete":
        break
```

### Error handling

Catch and recover from actor failures:

```python
try:
    state = await risky_operation(state)
    state = await another_step(state)
except ConnectionError:
    state["fallback"] = True
    state = await retry_handler(state)
except ValueError:
    pass            # swallow and continue
```

The compiler generates try-enter, try-exit, except-dispatch, and reraise
routers. When an actor inside the `try` block fails, the sidecar stamps
the error type and MRO onto `status.error`, and the except-dispatch
router matches it against the handler clauses.

Unmatched exceptions propagate to `x-sump` (the error sink).

### Fan-out (parallel execution)

Dispatch work to multiple actors in parallel:

```python
state["results"] = [
    analyzer_a(state["text"]),
    analyzer_b(state["text"]),
    analyzer_c(state["text"]),
]
state = await merge_results(state)
```

The compiler generates both a fan-out and a corresponding fan-in router to handle this. The fan-out router dispatches work to `analyzer_a`, `analyzer_b`, `and analyzer_c` in parallel. A hidden fan-in router then acts as an aggregator, collecting the results from all analyzers and placing them into `state["results"]`. Once all results are collected, the flow proceeds to the next step, `await merge_results(state)`, which can then operate on the aggregated data.

---

## What you cannot write in a flow

| Feature | Why not | Alternative |
|---|---|---|
| `for x in items:` | `for` loops not yet supported | Use `while` with an index |
| `result = a(b(state))` | Nested calls not allowed | Assign to state sequentially |
| `x, y = handler(state)` | Multiple assignment targets | Use single state variable |
| `MyClass(param=value)` | Instantiation with arguments not supported | Instantiate with `MyClass()` and rely on default `__init__` arguments. |
| `yield` / `yield from` | Flows don't produce events | Use ABI yields inside actor handlers |
| `import` / `global` | Flows are pure control flow | Put logic in actor handlers |

---

## Compilation

### What the compiler does

```
Flow source (.py)
    │
    ▼
  Parser ──→ validates syntax, extracts IR operations
    │
    ▼
  Grouper ──→ groups operations into routers, optimizes
    │
    ▼
  CodeGen ──→ generates router Python code
    │
    ▼
  routers.py + flow.dot (optional diagram)
```

### Compiler commands

**Compile:**
```bash
asya flow compile pipeline.py --output-dir compiled/ --plot --verbose
```

**Validate only (no code generation):**
```bash
asya flow validate pipeline.py
```

**Options:**
- `--output-dir` — where to write generated files
- `--plot` — generate Graphviz DOT and PNG flow diagrams
- `--plot-width N` — label width in diagrams (default: 50)
- `--max-iterations N` — loop iteration guard (default: 100)
- `--overwrite` — overwrite existing files
- `--verbose` — detailed output

### Generated files

| File | Contents |
|---|---|
| `routers.py` | Router functions + `resolve()` handler resolution |
| `flow.dot` | Graphviz diagram source (with `--plot`) |
| `flow.svg` | Visual flow diagram (with `--plot`) |

### Router naming

Generated routers have predictable names tied to source line numbers:

| Name pattern | Purpose |
|---|---|
| `start_{flow}` | Entry point |
| `end_{flow}` | Exit point |
| `router_{flow}_line_{N}_if` | Conditional branch at line N |
| `router_{flow}_line_{N}_seq` | Sequential mutations at line N |
| `router_{flow}_line_{N}_while_0` | Loop control at line N |

---

## Deployment

### 1. Write the flow

```python
# sentiment_pipeline.py
async def sentiment_pipeline(state: dict) -> dict:
    state = await preprocess(state)
    state = await analyze_sentiment(state)

    if state["sentiment"]["score"] < 0.3:
        state = await flag_for_review(state)

    state = await store_result(state)
    return state
```

### 2. Compile

```bash
asya flow compile sentiment_pipeline.py -o compiled/
```

### 3. Deploy router actors

Each generated router is deployed as an AsyncActor. Router actors need
the `ASYA_HANDLER_*` environment variables to resolve handler names to
actor names:

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: start-sentiment-pipeline
spec:
  image: my-routers:latest
  transport: sqs
  handler: compiled.routers.start_sentiment_pipeline
  env:
    - name: ASYA_HANDLER_PREPROCESS
      value: "handlers.preprocess"
    - name: ASYA_HANDLER_ANALYZE_SENTIMENT
      value: "handlers.analyze_sentiment"
    - name: ASYA_HANDLER_FLAG_FOR_REVIEW
      value: "handlers.flag_for_review"
    - name: ASYA_HANDLER_STORE_RESULT
      value: "handlers.store_result"
```

### 4. Deploy handler actors

Each handler is its own AsyncActor with its own image, scaling, and
resources:

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: analyze-sentiment
spec:
  image: sentiment-model:latest
  transport: sqs
  handler: handlers.analyze_sentiment
  scaling:
    minReplicaCount: 0
    maxReplicaCount: 10
  resources:
    requests:
      nvidia.com/gpu: 1
```

### 5. Send a message

The entry point is the start router's queue. Messages entering
`start-sentiment-pipeline` flow through the entire pipeline automatically.

### Handler resolution

At runtime, the `resolve()` function in `routers.py` maps handler names
from the flow source to actor names using environment variables:

```
Environment variable             Handler name              Actor name
────────────────────────────────  ────────────────────────  ──────────────────
ASYA_HANDLER_ANALYZE_SENTIMENT   handlers.analyze_sentiment  analyze-sentiment
```

The mapping is flexible — any unambiguous suffix of the handler name works:

```python
resolve("analyze_sentiment")                    # shortest suffix
resolve("handlers.analyze_sentiment")           # full path
```

---

## Design principles

### Flow = control flow only

A flow describes **which actors run and in what order**. It does not
describe what those actors do. This separation means:

- Actors are reusable across different flows
- Actors can be tested independently (no flow context needed)
- Flows can be changed without touching actor code
- Scaling decisions are per-actor, not per-flow

### State = message payload

Everything an actor needs must be in the message payload or in external
storage. There are no hidden channels between actors. This makes the data
flow explicit and debuggable — you can inspect any message in the queue to
see the full pipeline state at that point.

### Routers are actors too

Generated routers are deployed as regular AsyncActors. They consume from
a queue, process the message (rewrite `route.next`), and the sidecar
forwards the result. The only difference from handler actors is that
routers modify routing metadata instead of business data.

This means routers benefit from the same infrastructure: autoscaling,
retries, monitoring, and deployment. There is no special "router runtime"
— it's actors all the way down.

---

## Further reading

- [Flow Compiler Architecture](../architecture/asya-flow.md) — compiler
  internals: parser IR, grouper optimization, code generation
- [ABI Protocol Reference](abi-protocol.md) —
  yield-based metadata access used by generated routers and user handlers
