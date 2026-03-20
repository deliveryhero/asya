<!-- Type: Reference -->
# Asya Flow Compiler — Architecture

This document describes the **compiler internals** — how the Flow DSL
source is parsed, grouped into routers, and code-generated.

For the user-facing syntax, concepts, and deployment guide, see
[Flow DSL Reference](../reference/flow-dsl.md).

## Overview

The compiler transforms a Python function into a network of router actors.
Each router is a lightweight actor that inspects the payload and rewrites
`route.next` to steer messages through the pipeline. The compiler's job is
to automate what would otherwise be hand-written routing logic.

### The Router Problem

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

Flow automates router generation. You write the control flow once in
readable Python. The compiler produces the router actors. You focus on
business logic in your handler actors.

```
Flow source (.py)
    │
    ▼
  Parser ──→ Python AST → IR operations
    │
    ▼
  Grouper ──→ IR operations → Router list (optimized)
    │
    ▼
  CodeGen ──→ Router list → routers.py + flow.dot
```

Source: `src/asya-lab/asya_lab/flow/`

## Continuation-Passing Style (CPS)

Asya doesn't have a call stack. Each actor is a separate process (a
Kubernetes pod). There is no caller waiting for a return value. Instead,
the **message itself** carries the continuation — the list of actors that
should run next.

### Classic Nested Execution vs CPS

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

When you write a flow:

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

### State is in the Message

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

### Design Principles

**Flow = control flow only**

A flow describes **which actors run and in what order**. It does not
describe what those actors do. This separation means:

- Actors are reusable across different flows
- Actors can be tested independently (no flow context needed)
- Flows can be changed without touching actor code
- Scaling decisions are per-actor, not per-flow

**State = message payload**

Everything an actor needs must be in the message payload or in external
storage. There are no hidden channels between actors. This makes the data
flow explicit and debuggable — you can inspect any message in the queue to
see the full pipeline state at that point.

**Routers are actors too**

Generated routers are deployed as regular AsyncActors. They consume from
a queue, process the message (rewrite `route.next`), and the sidecar
forwards the result. The only difference from handler actors is that
routers modify routing metadata instead of business data.

This means routers benefit from the same infrastructure: autoscaling,
retries, monitoring, and deployment. There is no special "router runtime"
— it's actors all the way down.

## Compilation Pipeline

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

## 1. Parser

**File**: `parser.py`

The parser reads a Python source file, finds the flow function, and walks
the AST to produce a flat list of IR operations.

### Input validation

- Exactly one function with signature `def name(p: dict) -> dict:` (or
  `async def`)
- Parameter name: `p`, `payload`, or `state`
- Return type annotation: `dict`

### IR operations

The parser produces these operation types:

| IR Operation | Source construct | Fields |
|---|---|---|
| `ActorCall` | `p = handler(p)` | lineno, name, is_method, class_name |
| `ClassInstantiation` | `model = MLModel()` | lineno, var_name, class_name |
| `Mutation` | `p["key"] = value` | lineno, code |
| `Condition` | `if p["x"]: ...` | lineno, test, true_ops, false_ops |
| `WhileLoop` | `while cond: ...` | lineno, test, body_ops, is_infinite |
| `Break` | `break` | lineno |
| `Continue` | `continue` | lineno |
| `Return` | `return p` | lineno |
| `TryExcept` | `try: ... except: ...` | lineno, try_ops, handlers, finally_ops |
| `FanOutOp` | `p["x"] = [a(p), b(p)]` | lineno, target_key, actor_calls, pattern |

### Rejected constructs

The parser rejects with clear error messages:

- `for` loops (use `while` with index)
- `yield` / `yield from` (flows don't produce events)
- `import` / `global` / `nonlocal`
- `except ... as e:` binding (bare `except` or typed only)
- Nested `try`/`except`
- Class instantiation with non-default arguments
- Nested function calls (`a(b(p))`)
- Multiple assignment targets (`x, y = ...`)

## 2. Grouper

**File**: `grouper.py`

The grouper transforms the flat IR operation list into an optimized list
of `Router` objects. Each router becomes one deployed actor.

### Router types

| Type | Flag | Generated by | Purpose |
|---|---|---|---|
| Start | name prefix `start_` | Always | Entry point, initial routing |
| End | name prefix `end_` | Always | Exit point, clears route |
| Sequential | default | Mutations + unconditional actors | Batch mutations, append actors |
| Conditional | `condition` set | `if`/`elif`/`else` | Branch on payload value |
| Loop-back | `is_loop_back` | `while` loops | Re-insert loop body into route |
| Fan-out | `is_fan_out` | `p["x"] = [a(), b()]` | Parallel dispatch + aggregator |
| Try-enter | `is_try_enter` | `try:` block | Set `_on_error` header |
| Try-exit | `is_try_exit` | End of try body | Clear `_on_error` header |
| Except-dispatch | `is_except_dispatch` | `except:` clauses | Match error type, route to handler |
| Reraise | `is_reraise` | Unmatched exceptions | Raise RuntimeError |

### Optimization: mutation batching

Consecutive mutations are grouped into a single router:

```python
# Source: 3 mutations + 1 actor call
p["a"] = 1
p["b"] = 2
p["c"] = 3
p = handler(p)

# Grouper produces 1 router (not 4):
#   mutations: [p["a"]=1, p["b"]=2, p["c"]=3]
#   true_branch_actors: [handler]
```

### Loop handling

`while` loops generate a loop-back router that references itself in
`route.next`, creating a cycle in the actor graph:

```
                ┌──────────────────┐
                │ loop_back_router │
                │   if condition:  │
                │     next = [body,│──── true ───→ [body_actors...,
                │            self] │                loop_back_router]
                │   else:          │
                │     next = []    │──── false ──→ [continuation...]
                └──────────────────┘
```

For `while True:`, `break` statements generate conditional exits within
the loop body. The grouper tracks break targets to wire them to the
correct continuation point after the loop.

### Fan-out handling

Fan-out operations produce a generator router that yields N+1 messages:

- Index 0: parent payload → aggregator → continuation
- Index 1..N: slice payloads → individual actors → aggregator

Each message carries `x-asya-fan-in` headers for the aggregator to
reconstruct the result.

## 3. Code Generator

**File**: `codegen.py`

The code generator takes the router list and produces Python source code.

### Generated file structure

```python
# Header (source file reference, "DO NOT EDIT" warning)
# Router functions (one per Router object)
# resolve() function (handler name → actor name mapping)
```

### Router code pattern

All routers follow the same structure — read current route, compute new
route, emit payload:

```python
def router_flow_line_5_if(payload: dict):
    """Router for control flow and payload mutations"""
    p = payload
    _next_tail = yield "GET", ".route.next"    # read remaining route
    _next = []

    # ... mutations, conditions, actor appends ...

    yield "SET", ".route.next", _next + _next_tail  # write new route
    yield payload                                    # emit downstream
```

Routers are **generators** — they use ABI yield commands (GET/SET/DEL) to
interact with message metadata. See the
[ABI protocol specification](../reference/abi-protocol.md)
for details.

### Handler resolution

The `resolve()` function maps handler names from the flow source to
deployed actor names at runtime:

```
ASYA_HANDLER_MY_ACTOR="module.handler"
                 │          │
                 │          └── handler name (value)
                 └── actor name: my-actor (derived from env var suffix)
```

Resolution supports suffix matching — `resolve("handler")` matches
`module.handler` if unambiguous.

## 4. DOT Generator

**File**: `dot.py`

Optionally generates Graphviz DOT diagrams for visual inspection.

**Node colors**:
- Green (`lightgreen`): Start/End routers
- Wheat: Conditional and loop routers
- Blue (`lightblue`): User handler actors
- Yellow (`lightyellow`): Condition test labels

## CLI

```bash
# Compile with visualization
asya flow compile pipeline.py --output-dir compiled/ --plot

# Validate only
asya flow validate pipeline.py
```

Options: `--plot`, `--plot-width N`, `--max-iterations N` (loop guard,
default 100), `--overwrite`, `--verbose`.

## Testing

| Suite | Location | Coverage |
|---|---|---|
| Parser unit tests | `src/asya-lab/tests/flow/test_parser*.py` | ~95% |
| Grouper unit tests | `src/asya-lab/tests/flow/test_grouper*.py` | ~91% |
| CodeGen unit tests | `src/asya-lab/tests/flow/test_codegen*.py` | ~98% |
| Compiler API tests | `src/asya-lab/tests/flow/test_compiler*.py` | ~93% |
| DOT generator tests | `src/asya-lab/tests/flow/test_dot*.py` | 100% |
| Component tests | `testing/component/flow-compiler/` | E2E compilation + execution |

## What Flow Does NOT Do

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

## Related documents

- [Flow DSL Reference](../reference/flow-dsl.md) — user-facing syntax,
  CPS execution model, deployment guide
- [ABI Protocol Reference](../reference/abi-protocol.md) —
  yield-based metadata access used by generated routers
