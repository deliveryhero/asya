<!-- Type: Reference -->
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

### Stage 1: Parser (AST → IR)

**Source**: `src/asya-lab/asya_lab/flow/parser.py`

The parser walks the flow function's AST and produces a flat list of IR
operations. It handles flow function discovery, parameter normalization, and
statement classification.

#### Flow function discovery

The parser scans top-level function definitions for one matching the flow
signature: a function with a single `dict`-typed parameter and `dict` return
type.

```python
async def my_flow(state: dict) -> dict:  # matches
def my_flow(p: dict) -> dict:           # matches (sync)
def helper(x: int) -> int:              # does not match
```

The parameter name (`state`, `p`, `payload`) is normalized to `p` internally
via `_ParamNormalizer`, so all downstream IR uses `p` consistently.

#### Import map

The parser collects all `import` and `from...import` statements from the
module into a `{bare_name: qualified_name}` map:

```python
from tenacity import retry, stop_after_attempt
# produces: {"retry": "tenacity.retry", "stop_after_attempt": "tenacity.stop_after_attempt"}
```

This map is passed to the value extractor so positional arguments of bare
function calls can be resolved via `inspect.signature` on the qualified name.

#### Statement classification

Each statement in the flow function body maps to one IR node type:

| Python construct | IR type | What happens |
|---|---|---|
| `p = handler(p)` | `ActorCall` | Route to named handler actor |
| `p = await handler(p)` | `ActorCall` | Unwrap await, same as above |
| `p["key"] = value` | `Mutation` | Inline payload transformation |
| `p["key"] += 1` | `Mutation` | Augmented assignment |
| `if cond: ... else: ...` | `Condition` | Branches parsed recursively |
| `while cond: ...` | `WhileLoop` | Loop with optional condition |
| `while True: ...` | `WhileLoop(test=None)` | Guarded at runtime |
| `try: ... except: ...` | `TryExcept` | Exception routing |
| `p["r"] = [a(x), b(y)]` | `FanOutCall(literal)` | Parallel dispatch |
| `p["r"] = [a(x) for x in items]` | `FanOutCall(comprehension)` | Iterated fan-out |
| `p["r"] = await asyncio.gather(...)` | `FanOutCall(gather)` | Concurrent gather |
| `break` | `Break` | Exit loop |
| `continue` | `Continue` | Jump to loop start |
| `return state` | `Return` | Early exit |
| `raise` | `Raise` | Re-raise in except block |

#### Rules engine integration

When classifying a symbol (e.g. `tenacity.retry`, `handler_a`), the parser
consults the rules engine:

1. Check for `# asya: <action>` inline comment override (highest priority)
2. If no override and a rules engine is configured, call
   `engine.classify(symbol, module_path=...)`
3. Based on the result:
   - `ACTOR` / `UNFOLD` / `FLOW` → `ActorCall` (separate actor)
   - `INLINE` → `InlineCode` (inlined into router)
   - `CONFIG` → `InlineCode` with extracted values from the where-tree
   - No engine → all calls become `ActorCall` (backwards compatible)

For `CONFIG` rules with `where:` trees, the parser calls
`ValueExtractor.extract(call_node, rule)` to pull spec values and stores them
in `InlineCode.extracted_values`.

### Rules engine (AST-level classification)

**Source**: `src/asya-lab/asya_lab/compiler/rules.py`

The rules engine classifies Python symbols against an ordered list of compiler
rules using a most-specific-wins strategy.

#### TreatAs classifications

| Value | Meaning | IR result |
|-------|---------|-----------|
| `actor` | Separate actor, route through queue | `ActorCall` |
| `unfold` | Recursively compile (same-package helper) | `ActorCall` (future: inline expansion) |
| `flow` | Embedded sub-flow | `ActorCall` (future: flow composition) |
| `inline` | Inline code into router body | `InlineCode` |
| `config` | Extract configuration values | `InlineCode` + `extracted_values` |

#### Matching tiers

Rules are matched against symbols with four tiers (lower = more specific = wins):

| Tier | Pattern | Example | Matches |
|------|---------|---------|---------|
| 0 | Exact | `"tenacity.retry"` | `tenacity.retry` only |
| 1 | Prefix wildcard | `"tenacity.*"` | `tenacity.retry`, `tenacity.stop`, ... |
| 2 | Same-package dot | `"."` | Bare symbols in same root package |
| 3 | Global wildcard | `"*"` | Everything |

Within tier 1, longer prefixes win (`"tenacity.stop.*"` beats `"tenacity.*"`).

#### Default rules

```yaml
- match: "."    # same-package symbols
  treat-as: unfold

- match: "*"    # everything else
  treat-as: inline
```

Without user rules, bare symbols (same-package) are unfolded and dotted
symbols (external) are inlined.

#### User rules

Loaded from `.asya/config.compiler.rules.yaml`. User rules prepend to defaults,
so exact matches (tier 0) override wildcards:

```yaml
- match: "tenacity.retry"
  treat-as: config
  where:
    - param: stop
      where:
        - param: {arg: 0, kwarg: "max_attempt_number"}
          assign-to: spec.resiliency.retry.maxAttempts
```

#### Inline comment override

The highest-priority classification is the `# asya: <action>` inline comment:

```python
p = external.lib(p)  # asya: actor   — forces actor regardless of rules
p = local_helper(p)  # asya: inline  — forces inline regardless of rules
```

### Value extractor (AST-level extraction)

**Source**: `src/asya-lab/asya_lab/compiler/extractor.py`

The extractor pulls spec values from `ast.Call` nodes guided by `where:` trees
in compiler rules. It produces `{spec_path: value}` dicts that the compiler
writes into AsyncActor manifests.

#### Argument binding

Call arguments are bound to parameter names:

1. **Keywords**: always known (`func(delay=30)` → `{"delay": 30}`)
2. **Positional + `ParamSpec`**: rule declares both bindings
   (`param: {arg: 0, kwarg: "delay"}` → try kwarg first, then index)
3. **Positional + `inspect.signature`**: import the function at compile time
   and read its signature
4. **Positional fallback**: use index as string key (`"0"`, `"1"`, ...)

#### Where-tree walking

The `where:` tree is walked recursively:

- **Terminal node** (`param` + `assign-to`): extract value from bound arg,
  store at spec path
- **Non-terminal node** (`param` + `where`): bound arg is itself a Call or
  BinOp; bind its args and recurse into children
- **Match-only node** (`match` + `where`, no `param`): discriminator — only
  recurse if the current AST call's function name matches `match`
- **BinOp flattening**: `a() | b() | c()` flattened into three calls, each
  walked independently (tenacity's pipe combinator)

#### ParamSpec

Rules can declare both positional and keyword bindings:

```yaml
param: {arg: 0, kwarg: "name", type: "str"}
```

The extractor tries `kwarg` first (always known from keyword args), then falls
back to positional `arg` index. The `type` field is metadata for future
validation.

#### Static value extraction

The extractor handles these AST expression types:

| AST type | Example | Extracted value |
|----------|---------|-----------------|
| `ast.Constant` | `30`, `"hello"`, `True` | Literal value |
| `ast.Name` | `ValueError` | Identifier string |
| `ast.Tuple` | `(ValueError, TypeError)` | Comma-joined string |
| `ast.UnaryOp(USub)` | `-5` | Negated number |
| Complex expressions | `foo()`, `x + y` | `None` (not extractable) |

### IR specification

**Source**: `src/asya-lab/asya_lab/flow/ir.py`

All IR nodes inherit from `IROperation(lineno: int)`:

```python
# Actor invocation — routed through a queue to a separate actor
ActorCall(name: str, treat_as: str, extracted_values: dict[str, object])

# Inline code — executed inside the router function body
InlineCode(code: str, extracted_values: dict[str, object])

# Payload mutation — modifies payload fields inline
Mutation(code: str)

# Control flow
Condition(test: str, true_branch: list[IROperation], false_branch: list[IROperation])
WhileLoop(test: str | None, body: list[IROperation])    # None = while True
Break()
Continue()
Return()

# Error handling
TryExcept(body: list[IROperation], handlers: list[ExceptHandler], finally_body: list[IROperation])
ExceptHandler(error_types: list[str] | None, body: list[IROperation])   # None = bare except
Raise()

# Parallel execution
FanOutCall(target_key: str, pattern: str, actor_calls: list[tuple[str, str]],
           iter_var: str | None, iterable: str | None)
```

The IR is a flat tree: `Condition`, `WhileLoop`, and `TryExcept` contain nested
operation lists in their branches, but there is no separate "block" concept.
The grouper walks this tree to produce routers.

### Stage 2: Grouper (IR → Routers)

**Source**: `src/asya-lab/asya_lab/flow/grouper.py`

The grouper transforms the flat IR operation list into a list of `Router`
execution units. Each router becomes a separate async function in the
generated code.

#### What is a Router?

A `Router` is an execution unit with:

- **Mutations**: payload transformations executed inline (fused from
  consecutive `Mutation` / `InlineCode` IR nodes)
- **Routing decision**: conditional branch, loop-back, exception dispatch
- **Continuation**: list of downstream actor names to visit next

Key fields:

```python
Router:
  name: str                              # e.g. "router_my_flow_line_5_if"
  mutations: list[Mutation]              # inline payload edits
  condition: Condition | None            # if-test (None = unconditional)
  true_branch_actors: list[str]          # actors if condition true
  false_branch_actors: list[str]         # actors if condition false
  is_loop_back: bool                     # re-inserts loop body actors
  guard_max_iter: int | None             # max iterations (while True guard)
  is_try_enter: bool                     # sets _on_error header
  is_try_exit: bool                      # clears _on_error on success
  is_except_dispatch: bool               # matches error type, routes to handler
  is_reraise: bool                       # raises for unhandled exceptions
  is_fan_out: bool
  fan_out_op: FanOutCall | None
```

#### Grouping rules

1. **Mutation fusion**: consecutive mutations are batched into the next
   router's `mutations` list — no separate actor for mutations
2. **Condition**: creates a conditional router; branches processed recursively
   with convergence labels for rejoin points
3. **WhileLoop**: `while True` creates a self-referencing loop-back router
   with max-iterations guard; `while cond` creates a condition router with
   self-reference in the true branch
4. **TryExcept**: creates four routers: try-enter (set `_on_error` header),
   try-exit (clear header on success), except-dispatch (match error type via
   MRO), reraise (unhandled)
5. **FanOut**: creates a fan-out router + aggregator reference

#### Convergence resolution

Branches (if/else, try/except) must reconverge. The grouper uses placeholder
labels (`CONVERGENCE_0`, `LOOP_EXIT_0`, etc.) during grouping, then resolves
them to actual actor names in a final pass.

#### Optimization

- **Start router merger**: if the first router after `start_` only has
  mutations (no branching), merge into `start_` to save one actor hop

### Stage 3: Code generator (Routers → Code)

**Source**: `src/asya-lab/asya_lab/flow/codegen.py`

The code generator emits Python source from the router list. Each router
becomes an `async def` function using the ABI yield protocol.

#### Generated router types

| Router type | Generated behavior |
|---|---|
| Start | Apply mutations, `SET .route.next[:0]` to prepend downstream actors |
| Conditional | `if condition:` branch, append actors to `_next` list |
| Loop-back | Re-insert loop body actors; for `while True`: check iteration guard via `.route.prev` count |
| Try-enter | `SET .headers._on_error` to except-dispatch router name |
| Try-exit | Clear `_on_error` header; chain finally + continuation actors |
| Except-dispatch | Read `.status.error.type` + `.status.error.mro`, match handlers |
| Reraise | Raise `RuntimeError` for unhandled exceptions |
| Fan-out | Emit N+1 messages: parent + N sub-agents with `x-asya-fan-in` headers |
| End | `SET .route.next` to `[]` (pipeline completion) |

#### Handler resolution

The generated `resolve()` function maps handler names from the flow source to
actor names using `ASYA_HANDLER_*` environment variables:

```
ASYA_HANDLER_ANALYZE_SENTIMENT="handlers.analyze_sentiment"
```

Resolution uses suffix matching — any unambiguous suffix works:

```python
resolve("analyze_sentiment")              # shortest suffix
resolve("handlers.analyze_sentiment")     # full path
```

Ambiguous matches raise an error listing candidates.

#### Single-actor flows

When a flow has exactly one actor call and no branching, the code generator
emits a `FLOW_METADATA` constant instead of router functions:

```python
FLOW_METADATA = {
    "flow_name": "my_flow",
    "type": "single-actor",
    "actor": "handler_name",
    "labels": {"asya.sh/flow": "my_flow", "asya.sh/flow-role": "entrypoint"},
}
```

#### Router naming convention

| Pattern | Purpose |
|---|---|
| `start_{flow}` | Entry point |
| `end_{flow}` | Exit point |
| `router_{flow}_line_{N}_if` | Conditional at line N |
| `router_{flow}_line_{N}_seq` | Sequential mutations at line N |
| `router_{flow}_line_{N}_while_{id}` | Loop condition check |
| `router_{flow}_line_{N}_loop_back_{id}` | Loop re-insertion |
| `fanout_{flow}_line_{N}` | Fan-out dispatch |
| `fanin_{flow}_line_{N}` | Fan-out aggregator |
| `router_{flow}_line_{N}_try_enter_{id}` | Try entry |
| `router_{flow}_line_{N}_try_exit_{id}` | Try success path |
| `router_{flow}_line_{N}_except_dispatch_{id}` | Exception dispatch |
| `router_{flow}_line_{N}_reraise_{id}` | Unhandled exception |

### Future: adapter generation

When a flow calls a decorated function (e.g. `@tool(...)`) that doesn't
conform to the `dict -> dict` actor protocol, the compiler will generate
an adapter handler. See aint [ch0h] for the full design.

The adapter shape is inferred from the call site, not from templates:

```python
state["result"] = greet_user(state["tool_call"]["args"])  # asya: actor
```

The parser extracts input/output paths from the AST and stores them on the
`ActorCall` IR node. The code generator reads these IR fields and emits the
adapter — it never touches AST nodes directly.

| Concern | Layer | Why |
|---------|-------|-----|
| Decorator pattern matching | Rules (AST) | Needs symbol names |
| Parameter extraction | Extractor (AST) | Needs `ast.Call` arg binding |
| Input/output path inference | Parser (AST → IR) | Needs `ast.Subscript` chains |
| "Needs adapter?" decision | IR | `input_path is not None` on `ActorCall` |
| Adapter code emission | Codegen (IR → Code) | Reads IR fields only |

---

## Further reading

- [ABI Protocol Reference](abi-protocol.md) —
  yield-based metadata access used by generated routers and user handlers
