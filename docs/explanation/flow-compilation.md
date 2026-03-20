<!-- Type: Explanation -->

# Flow Compilation: CPS and the Router Problem

Background on why the Flow DSL exists, what problem it solves, and how
the compiler transforms Python control flow into a network of stateless
router actors using Continuation-Passing Style (CPS).

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

## Compiler architecture

### Pipeline overview

```
Source (.py)
     |
     v
  [Parser]  ←── Rules Engine (AST-level classification + extraction)
     |               ↑
     |          Value Extractor (AST Call → spec values)
     v
  IR Operations (ActorCall, Mutation, Condition, ...)
     |
     v
  [Grouper]
     |
     v
  Routers (execution units)
     |
     v
  [CodeGen]
     |
     v
  routers.py + flow.dot
```

Each stage has a clear input/output contract:

| Stage | Input | Output | Operates on |
|-------|-------|--------|-------------|
| **Parser** | Python source (AST) | `(flow_name, [IROperation])` | AST nodes |
| **Rules Engine** | Symbol name (string) | `TreatAs` classification | Strings (AST-derived) |
| **Value Extractor** | `ast.Call` + `CompilerRule` | `{spec_path: value}` | AST nodes |
| **Grouper** | `[IROperation]` | `[Router]` | IR only |
| **CodeGen** | `[Router]` | Python source string | IR only |

The boundary is strict: **rules and extraction operate at AST level** (they need
call arguments, decorator lists, function names). Everything downstream — grouper
and codegen — operates on **IR only** and never touches AST nodes.

---

## See also

- [Flow DSL Reference](../reference/flow-dsl.md) — syntax rules, IR spec,
  compiler stage details, and generated router tables
- [ABI Protocol Reference](../reference/abi-protocol.md) —
  yield-based metadata access used by generated routers and user handlers
