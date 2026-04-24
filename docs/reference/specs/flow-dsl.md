---
description: "Flow DSL spec: Python syntax rules, compilation semantics, fan-out/fan-in, conditional routing"
---

# Flow DSL

Syntax rules, IR specification, compiler stages, and generated router tables
for the Flow DSL.

For background on why the Flow DSL exists, the router problem it solves,
and how CPS compilation works, see
[Flow Compiler Architecture](../components/lab-flow-compiler.md).

---

## What is the Flow DSL?

The Flow DSL is a restricted subset of Python for describing how actors are
connected. You write a function that looks like ordinary sequential Python
code. The compiler transforms it into a network of **router actors** that
steer messages through your pipeline at runtime.

```python
@flow
def review_pipeline(p: dict) -> dict:
    p = classify(p)

    if p["category"] == "urgent":
        p = escalate(p)
    else:
        p = standard_review(p)

    try:
        p = notify(p)
    except ConnectionError:
        p = fallback_notify(p)

    return p
```

This compiles into router actors that handle sequencing, branching, error
routing, and merging. You deploy the routers alongside your handler actors
and Asya runs the pipeline.

### Flow DSL vs Actor handlers

A flow and an actor handler both have a `dict -> dict` signature, but they
are fundamentally different:

| | Flow DSL | Actor handler |
|---|---|---|
| **Purpose** | Describes routing between actors | Executes business logic |
| **Runs as** | Compiled to router actors (CPS) | Deployed as a pod with sidecar |
| **Allowed** | Control flow only: `if`, `while`, `try/except`, `break`, `continue`, `return` | Full Python: imports, classes, I/O, yields, FLY events |
| **Forbidden** | `yield`, `for`, free variables, imports, side effects | N/A — full Python |
| **State** | Single `p` variable (the payload dict) | Can use `yield "GET"`, `yield "SET"`, state proxy |
| **Errors** | `try/except` compiles to resiliency rules in manifests | Errors bubble to sidecar for policy dispatch |

The Flow DSL is **pure control flow** — it describes the shape of the pipeline.
All computation happens in actor handlers. Think of it as a wiring diagram:
the flow says "connect A to B, branch on condition C, retry on error D";
the actors do the actual work.

### What flows support

| Construct | Example | Compiles to |
|-----------|---------|-------------|
| Actor calls | `p = handler(p)` | Route entry in `route.next` |
| Payload mutations | `p["key"] = "value"` | Inline code in router function |
| Conditionals | `if p["x"]: ... else: ...` | Conditional router with branch routing |
| While loops | `while p["n"] < 3: ...` | Loop-back router with self-reference |
| Break / continue | `break`, `continue` | Exit / restart loop via route overwrite |
| Early return | `return p` | Clear `route.next` → x-sink |
| Try/except/finally | `try: ... except E: ...` | Except router + resiliency policies and rules in manifests |
| Raise (in except) | `raise` | Terminate flow (route to x-sink) |
| Fan-out | `p["r"] = [a(x) for x in items]` | Fan-out router + fan-in aggregator |
| Flow composition | `@flow` sub-functions | Inlined at compile time |
| Context managers | `with timeout(30): ...` | Config extraction (via compiler rules) |

### What flows do NOT support

| Construct | Why | Alternative |
|-----------|-----|-------------|
| `for x in items:` | Replaced by fan-out comprehensions | `p["r"] = [actor(x) for x in items]` |
| `yield` / `yield from` | Flows are not generators | Use yields inside actor handlers |
| `import` / `global` | Flows are pure control flow | Put logic in actor handlers |
| Free variables | Only `p` is allowed | Pass data via `p["key"]` |
| `result = a(b(p))` | Nested calls | Assign sequentially: `p = b(p); p = a(p)` |
| `except E as e:` | No exception binding | Error details in `status.error` (read via ABI) |
| `try: ... else:` | Not supported | Use a separate `if` after the try block |
| Side effects (`print`) | Not a control flow construct | Put in actor handlers |

**There is no `AsyncFlow` CRD.** A flow is a group of `AsyncActor`
resources linked by the `asya.sh/flow` label. The compiler sets this
label (along with `asya.sh/role` to distinguish `start`, `end`,
`router`, and `actor` roles) on every generated manifest. Query all
actors in a flow with `kubectl get asya -l asya.sh/flow=<name>`. The
actor remains the single Kubernetes primitive — flows are a labeling
convention on top of it.

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
actors into `route.next` on each iteration.

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
    p = risky_operation(p)
    p = another_step(p)
except ConnectionError:
    p["fallback"] = True
    p = retry_handler(p)
except ValueError:
    p = log_and_continue(p)
finally:
    p = cleanup(p)
```

The compiler generates one **except_router** per `except` clause and
injects **resiliency policies and rules** into the manifests of every
actor inside the `try` body. When an actor fails, the sidecar matches
the error type against the rules and routes to the correct except_router. The
except_router overwrites `route.next` with the handler's continuation
path (including `finally` actors).

Supported patterns: typed exceptions, tuple types (`except (A, B):`),
FQN types (`except openai.RateLimitError:`), bare `except:` (catch-all),
`raise` in except body (terminates flow), nested try/except, and
`finally` blocks.

See [usage/guide-error-handling.md](../../usage/guide-error-handling.md) for
detailed examples and runtime flow diagrams.

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

See the full table in the [What flows do NOT support](#what-flows-do-not-support) section above.

---

## Compilation

### What the compiler does

```
Flow source (.py)
    │
    ▼
  Parser ──→ validates syntax, extracts operations
    │
    ▼
  CodeGen ──→ generates router Python code + resiliency policies and rules
    │
    ▼
  Analyzer ──→ extracts graph topology from generated code
    │
    ▼
  GraphGen ──→ renders DOT, Mermaid, JSON visualizations
    │
    ▼
  Templater ──→ stamps AsyncActor manifests (if .asya/ configured)
    │
    ▼
  routers.py + graph.json + flow.dot + manifests/
```

### Compiler commands

**Compile:**
```bash
asya flow compile pipeline.py --output-dir compiled/ --plot --verbose
```

**Validate (runs full compilation in memory, no files written):**
```bash
asya flow validate pipeline.py
```

**Options:**
- `--output-dir` — where to write generated files
- `--plot` — generate Graphviz DOT and PNG flow diagrams
- `--verbose` — detailed output

### Generated files

| File | Contents |
|---|---|
| `routers.py` | Router functions + `resolve()` handler resolution |
| `graph.json` | Graph topology (nodes, edges, groups) |
| `flow.dot` | Graphviz diagram source (with `--plot`) |
| `flow.mmd` | Mermaid flowchart (with `--plot`) |
| `flow.png` | Rendered diagram (with `--plot`, requires graphviz) |
| `manifests/` | AsyncActor YAML manifests (if `.asya/` configured) |

### Router naming

Generated routers have content-based slug names for readability:

| Name pattern | Purpose |
|---|---|
| `start_{flow}` | Entry point |
| `router_{flow}_if_{slug}` | Conditional branch (slug derived from condition) |
| `router_{flow}_seq_{slug}` | Sequential mutations (slug from mutation content) |
| `router_{flow}_while_{slug}` | Loop control (slug from loop body) |
| `router_{flow}_except_{slug}` | Error handler routing (slug from exception type) |
| `fanout_{flow}_{slug}` | Fan-out dispatch (slug from target) |
| `fanin_{flow}_{slug}` | Fan-out aggregator (slug from aggregation key) |

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

## Stage 1: Parser (AST → IR)

**Source**: `src/asya-lab/asya_lab/flow/parser.py`

The parser walks the flow function's AST and produces a flat list of IR
operations. It handles flow function discovery, parameter normalization, and
statement classification.

### Flow function discovery

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

### Import map

The parser collects all `import` and `from...import` statements from the
module into a `{bare_name: qualified_name}` map:

```python
from tenacity import retry, stop_after_attempt
# produces: {"retry": "tenacity.retry", "stop_after_attempt": "tenacity.stop_after_attempt"}
```

This map is passed to the value extractor so positional arguments of bare
function calls can be resolved via `inspect.signature` on the qualified name.

### Statement classification

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

### Rules engine integration

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

## Symbol classification

**Source**: `src/asya-lab/asya_lab/compiler/rules.py`, `src/asya-lab/asya_lab/flow/parser.py`

Every function call in a flow is classified as one of five `treat-as` values.
The classification determines whether the call creates an actor boundary,
runs inline in the router, or extracts configuration.

### TreatAs values

| Value | Meaning | Effect |
|-------|---------|--------|
| `actor` | Separate actor, route through queue | `ActorCall` — creates a queue hop |
| `flow` | Embedded sub-flow, compile recursively | Expand body + create visual group in graph |
| `unfold` | Expand function body into current flow | Expand body (no visual group) |
| `inline` | Paste code into router body | `Mutation` — runs inside router process |
| `config` | Extract configuration values | Strip decorator/context manager, inject into manifest |

### Implicit defaults

When no explicit annotation or rule matches, the parser classifies based on
where the function is defined:

| Origin | Default | Rationale |
|--------|---------|-----------|
| Local function (defined in same file) | `unfold` | Expand body into the flow |
| Imported function (from external package) | `inline` | Treat as payload code |
| Bare name (not defined, not imported) | `actor` | Assumed to be a deployed actor |

### Explicit overrides (highest to lowest priority)

1. **Inline comment** — `# asya: <treat-as>` on the call site:

   ```python
   p = external.lib(p)  # asya: actor   — force actor
   p = local_helper(p)  # asya: inline  — force inline
   ```

2. **Definition-site decorator** — `@actor`, `@flow`, `@inline`, `@unfold`:

   ```python
   @actor
   def validate(p: dict) -> dict: ...

   @inline
   def inject_trace(p: dict) -> dict: ...
   ```

3. **Call-site wrapper** — `actor(fn)(p)`, `inline(fn)(p)`:

   ```python
   p = actor(validate)(p)
   p = inline(inject_trace)(p)
   ```

4. **Config rule** — where-tree rules in `.asya/config.compiler.rules.yaml`:

   ```yaml
   - match: "tenacity.retry"
     treat-as: config
     where:
     - param: stop
       flatten-on: "|"
       where:
       - match: "stop_after_attempt"
         where:
         - param: max_attempt_number
           assign-to: spec.resiliency.policies.default.maxAttempts
   ```

5. **Implicit defaults** — see table above

All five `treat-as` values are supported via all mechanisms.

### Config extraction

Rules with `treat-as: config` extract values from decorator arguments or
context manager parameters and inject them into AsyncActor manifests.
The `where:` tree walks nested AST elements, and `assign-to` maps extracted
values to AsyncActor spec paths:

```yaml
# Context manager: asyncio.timeout(30) -> spec.resiliency.timeout.actor: 30
- match: "asyncio.timeout"
  treat-as: config
  where:
  - param: delay
    assign-to: spec.resiliency.timeout.actor

# Decorator: @retry(stop=stop_after_attempt(3)) -> maxAttempts: 3
# Supports BinOp: stop=stop_after_attempt(5) | stop_after_delay(30)
- match: "tenacity.retry"
  treat-as: config
  where:
  - param: stop
    flatten-on: "|"
    where:
    - match: "stop_after_attempt"
      where:
      - param: max_attempt_number
        assign-to: spec.resiliency.policies.default.maxAttempts
    - match: "stop_after_delay"
      where:
      - param: max_delay
        assign-to: spec.resiliency.policies.default.maxDuration
```

The parser auto-detects scope from Python syntax — no `scope:` field needed:
- Context managers (`with foo():`) apply config to all actors in the `with` body
- Decorators (`@foo`) apply config to the decorated function only

Config decorators are added to `ASYA_IGNORE_DECORATORS` env var so the
runtime strips them at handler load time.

Default rules ship in `src/asya-lab/asya_lab/defaults/compiler.rules.yaml`.
User rules in `.asya/config.compiler.rules.yaml` extend (not replace) defaults.

## Value extractor (AST-level extraction)

**Source**: `src/asya-lab/asya_lab/compiler/extractor.py`

The extractor pulls spec values from `ast.Call` nodes guided by `where:` trees
in compiler rules. It produces `{spec_path: value}` dicts that the compiler
writes into AsyncActor manifests.

### Argument binding

Call arguments are bound to parameter names:

1. **Keywords**: always known (`func(delay=30)` → `{"delay": 30}`)
2. **Positional + `ParamSpec`**: rule declares both bindings
   (`param: {arg: 0, kwarg: "delay"}` → try kwarg first, then index)
3. **Positional + `inspect.signature`**: import the function at compile time
   and read its signature
4. **Positional fallback**: use index as string key (`"0"`, `"1"`, ...)

### Where-tree walking

The `where:` tree is walked recursively:

- **Terminal node** (`param` + `assign-to`): extract value from bound arg,
  store at spec path
- **Non-terminal node** (`param` + `where`): bound arg is itself a Call;
  bind its args and recurse into children
- **Match-only node** (`match` + `where`, no `param`): discriminator — only
  recurse if the current AST call's function name matches `match`
- **BinOp flattening** (`flatten-on: "|"`): when a non-terminal param
  resolves to a BinOp using the specified operator, flatten into a list of
  calls and try each against the `where:` children independently. Without
  `flatten-on`, BinOp expressions are not traversed.

  Example: `stop=stop_after_attempt(5) | stop_after_delay(30)` is flattened
  into `[stop_after_attempt(5), stop_after_delay(30)]`, each matched
  against the `match:` discriminators in the `where:` tree.

  Supported operators: `"|"` (BitOr), `"&"` (BitAnd), `"+"` (Add).

### ParamSpec

Rules can declare both positional and keyword bindings:

```yaml
param: {arg: 0, kwarg: "name", type: "str"}
```

The extractor tries `kwarg` first (always known from keyword args), then falls
back to positional `arg` index. The `type` field is metadata for future
validation.

### Static value extraction

The extractor handles these AST expression types:

| AST type | Example | Extracted value |
|----------|---------|-----------------|
| `ast.Constant` | `30`, `"hello"`, `True` | Literal value |
| `ast.Name` | `ValueError` | Identifier string |
| `ast.Tuple` | `(ValueError, TypeError)` | Comma-joined string |
| `ast.UnaryOp(USub)` | `-5` | Negated number |
| Complex expressions | `foo()`, `x + y` | `None` (not extractable) |

## IR specification

**Source**: `src/asya-lab/asya_lab/flow/parser.py` (IR dataclasses defined inline, no separate ir.py)

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

## Stage 2: Code generator (Operations → Code)

**Source**: `src/asya-lab/asya_lab/flow/codegen.py`

The code generator walks the operation list from the parser and directly
emits router functions. Each operation type maps to a router generation
strategy:

### Generated router types

| Router type | Generated behavior |
|---|---|
| Start | Apply mutations, `SET .route.next[:0]` to prepend downstream actors |
| Seq | Batch mutations + chain actors sequentially |
| Conditional | `if condition:` branch, append actors to `_next` list per branch |
| Loop | Re-insert loop body actors + self-reference; exit via `SET .route.next` |
| Except | `SET .route.next` (overwrite) to handler + finally + continuation |
| Fan-out | Emit N+1 messages: parent + N sub-agents with `x-asya-fan-in` headers |
| Fan-in | Aggregator (hidden, generated alongside fan-out) |

### Try/except compilation

For `try/except` blocks, the code generator:

1. Creates one **except_router** per `except` clause — each overwrites
   `route.next` with the handler's continuation path (using SET, not prepend)
2. Records resiliency **policies** and **rules** for every actor in the
   try body — these are later injected into actor manifests by the templater
3. Includes `finally` actors in both the success path and every error path

The rules link actors to their except_routers via the sidecar's
`resiliency.rules` first-match dispatch — no Python-level type matching needed.

### Handler resolution

The generated `resolve()` function maps handler names from the flow source to
actor names using `ASYA_HANDLER_*` environment variables. Resolution uses
suffix matching — any unambiguous suffix works.

### Single-actor flows

When a flow has exactly one actor call and no branching, the code generator
emits a `FLOW_METADATA` constant instead of router functions.

## Adapter generation

When a flow calls a decorated function (e.g. `@tool(...)`) that doesn't
conform to the `dict -> dict` actor protocol, the compiler generates
an adapter handler that bridges the two signatures:

```python
state["result"] = greet_user(state["tool_call"]["args"])  # asya: actor
```

The parser extracts input/output paths from the AST. The code generator emits a standalone adapter Python file that wraps `greet_user` in the actor protocol.

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

## See also

- [Flow Compiler Architecture](../components/lab-flow-compiler.md) — why the Flow DSL
  exists, the router problem, CPS model, and design principles
- [ABI Protocol Reference](abi-protocol.md) —
  yield-based metadata access used by generated routers and user handlers
- [Error Handling in Flows](../../usage/guide-error-handling.md) —
  try/except patterns, runtime flow diagrams, manifest examples
- [Configuring Error Handling](../../setup/guide-error-handling.md) —
  resiliency policies, rules, and error routing at the platform level
