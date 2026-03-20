# Asya Flow Compiler — Architecture

This document describes the **compiler internals** — how the Flow DSL
source is parsed, code-generated into routers, analyzed for routing
edges, and rendered as graphs.

For the user-facing syntax, concepts, and deployment guide, see
[Flow DSL Reference](../specs/flow-dsl.md).

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
async def urgency_router(payload):
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
  Parser ──→ Python AST → Operations + Config
    │
    ▼
  CodeGen ──→ Operations → routers.py
    │
    ▼
  Manifests ──→ Actor metadata → AsyncActor YAML
    │
    ▼
  Analyzer ──→ Yield analysis → GraphData
    │
    ▼
  GraphGen ──→ GraphData → graph.json + DOT + Mermaid + SVG
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
async def pipeline(data):
    validated = await validate(data)       # call, wait, return
    enriched = await enrich(validated)     # call, wait, return
    result = await process(enriched)       # call, wait, return
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
flow.py ──→ [1. Parse] ──→ [2. CodeGen] ──→ [3. Manifests] ──→ [4. Analyze] ──→ [5. GraphGen] ──→ FlowInfo
```

Each stage has a clear input/output contract:

| Stage | Input | Output | Description |
|---|---|---|---|
| **Parser** | Python source (AST) | `ParseResult` (operations, actors, resiliency rules) | AST → flat operation list |
| **CodeGen** | `ParseResult` | `routers.py` | Operations → Python router code (direct, no grouper) |
| **Manifests** | `ParseResult` | AsyncActor XR YAML (kustomize base/) | Actor metadata → deployment manifests |
| **Analyzer** | routers.py + handler files + manifests | `GraphData` | Yield analysis: extract routing edges from code |
| **GraphGen** | `GraphData` | graph.json + flow.dot + flow.mmd + flow.svg | Render graph in multiple formats |

The boundary is strict: **rules and config extraction operate at AST level** (they
need call arguments, decorator lists, function names) and fold into `ParseResult`.
Everything downstream — codegen, manifests, analyzer, and graph generation —
operates on parsed results and generated artifacts, never on AST nodes directly.

## 1. Parser

**File**: `parser.py`

The parser reads a Python source file, finds the flow function, and walks
the AST to produce a flat list of operations and extracted configuration.

### Input validation

- Exactly one function with signature `def name(p: dict) -> dict:` (or
  `async def`)
- Parameter name: `p`, `payload`, or `state`
- Return type annotation: `dict`

### Operation types

The parser produces five operation types:

| Operation | Source construct | Fields |
|---|---|---|
| `ActorCall` | `p = handler(p)` | lineno, name, source_file |
| `Mutation` | `p["key"] = value` | lineno, code |
| `Conditional` | `if p["x"]: ...` | lineno, test, true_branch, false_branch |
| `Loop` | `while cond: ...` | lineno, test, body (`test: None` for `while True`) |
| `FanOut` | `p["x"] = [a(p), b(p)]` | lineno, target_key, actor_calls, pattern |

Previous IR types that no longer exist as separate operations:

| Eliminated type | Where it went |
|---|---|
| `Break` | Codegen emits routing to convergence point after the loop |
| `Continue` | Codegen emits routing to loop top (self-referencing router) |
| `Return` | Codegen emits routing to exit actor |
| `TryExcept` / `ExceptHandler` | Parser extracts error types into `resiliency_rules` in `ParseResult` |

### ParseResult

The parser returns a `ParseResult` containing the operations and all
extracted configuration:

```python
@dataclass
class ParseResult:
    flow_name: str
    operations: list[Operation]
    actors: list[ActorRef]          # resolved handler metadata
    resiliency_rules: list[dict]    # from try/except → manifest resiliency.rules
    extracted_configs: list[dict]   # from decorator/context manager extraction
    ignore_decorators: list[str]    # FQNs for ASYA_IGNORE_DECORATORS env var
    imports: list[str]
    constants: list[str]
```

### Rejected constructs

The parser rejects with clear error messages:

- `for` loops (use `while` with index)
- `yield` / `yield from` (flows don't produce events)
- `import` / `global` / `nonlocal`
- Class instantiation with non-default arguments
- Nested function calls (`a(b(p))`)
- Multiple assignment targets (`x, y = ...`)
- `try`/`except` without a matching compiler rule (with a rule,
  error types are extracted into `resiliency_rules` instead)

**Note**: The grouper stage has been eliminated. The code generator operates
directly on the parser's operation list, producing router functions without
an intermediate Router representation. Each control flow point becomes a
router function with the invariant: one decision per router.

## 2. Code Generator

**File**: `codegen.py`

The code generator receives `ParseResult` and produces Python source code
directly from the operations list. Each control flow point becomes a router
function. Sequential actors between control flow points are grouped into a
single router.

**Invariant: one decision per router.** Each generated router function has
at most one level of if/else. Nested control flow in the flow DSL produces
a chain of routers, not nested Python blocks inside a single function. This
keeps the yield analyzer trivial — it only needs to extract conditions from
flat if/else blocks.

The mapping from operations to generated code:

- `ActorCall` → `_next.append(resolve("handler_name"))`
- `Mutation` → raw code string inserted into the router body
- `Conditional` → `if test: ... else: ...` with routing in branches
- `Loop` → self-referencing router (condition check + body routing)
- `FanOut` → multi-yield pattern (parallel dispatch + aggregator)

### Generated file structure

```python
# Header (source file reference, "DO NOT EDIT" warning)
# Router functions (one per control flow point)
# resolve() function (handler name → actor name mapping)
```

### Router code pattern

All routers follow the same structure — read current route, compute new
route, emit payload:

```python
async def router_flow_line_5_if(payload: dict):
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
[ABI protocol specification](../specs/abi-protocol.md)
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

## 3. Manifest Generator

**File**: `templater.py`

The manifest generator takes `ParseResult` and produces AsyncActor XR YAML
files into a kustomize `base/` directory. Each actor in the flow gets a
manifest with handler reference, labels (including `asya.sh/flow` and
`asya.sh/flow-role`), extracted configuration from compiler rules, and
decorator stripping instructions (`ASYA_IGNORE_DECORATORS` env var).

The `base/` directory is compiler-owned and always overwritten on
recompilation. Platform customizations go in a separate `common/` overlay
that the compiler never touches.

## 4. Yield Analyzer

**File**: `analyzer.py`

The yield analyzer extracts routing edges from generated routers,
user-written handlers, and manifest error routes to produce a unified
`GraphData` structure.

It parses Python source via `ast.parse()`, walking handler function ASTs
to find yield statements matching ABI patterns (`yield "SET", ".route.next",
[...]`). For each yield inside an if/else block, the enclosing condition is
captured as the edge label.

### Three handler categories

1. **Generated routers** (`routers.py`): Full yield analysis — all patterns
   are analyzable since the compiler generated them. The one-decision-per-router
   invariant means the analyzer only encounters flat if/else blocks.
2. **User-written handlers** (project source): Best-effort yield analysis
   via `inspect.getsource()` or direct file read. Captures `yield "SET",
   ".route.next"` patterns for override edges.
3. **External package handlers** (site-packages): Best-effort via
   `inspect.getsource()`. Opaque node if source is unavailable
   (C extensions, bytecode-only).

### Merge algorithm

1. Parse generated routers → extract routing chains
2. Parse user handlers → extract override edges
3. Parse manifests → `resiliency.rules[*].thenRoute` → error routing edges
4. Merge: chains + overrides + error edges. Override edges from user handlers
   replace flow-declared edges (marked `override: true`).

## 5. Graph Generator

**File**: `graphgen.py`

Three renderers consuming the same `GraphData`:

```python
def to_dot(data: GraphData, flow_name: str) -> str: ...
def to_mermaid(data: GraphData, flow_name: str) -> str: ...
def to_json(data: GraphData, flow_name: str) -> dict: ...
```

Each renderer iterates nodes and edges from `GraphData` and applies format-
specific styling. The DOT renderer uses node colors to distinguish actor
types (green for entry/exit, wheat for routers, blue for user handlers).
The Mermaid renderer produces equivalent diagrams for documentation contexts
where Graphviz is unavailable.

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
| CodeGen unit tests | `src/asya-lab/tests/flow/test_codegen*.py` | ~98% |
| Analyzer unit tests | `src/asya-lab/tests/flow/test_analyzer*.py` | Yield pattern extraction + merge |
| GraphGen unit tests | `src/asya-lab/tests/flow/test_graphgen*.py` | DOT + Mermaid + JSON rendering |
| Compiler API tests | `src/asya-lab/tests/flow/test_compiler*.py` | ~93% |
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

- [Flow DSL Reference](../specs/flow-dsl.md) — user-facing syntax,
  CPS execution model, deployment guide
- [ABI Protocol Reference](../specs/abi-protocol.md) —
  yield-based metadata access used by generated routers
