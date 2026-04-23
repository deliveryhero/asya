---
description: "Compiler rules spec: extensible rules for decorators, context managers, custom call patterns"
---

# Compiler Rules

Formal specification for the compiler rules system — the extensible knowledge
base that maps Python AST elements (decorators, context managers, function calls)
to AsyncActor manifest fields.

For a practical guide with examples, see
[usage/guide-compiler-rules.md](../../usage/guide-compiler-rules.md).

---

## Overview

Compiler rules are a config-driven mechanism for teaching the flow compiler how
to interpret Python constructs it encounters in flow source files. Each rule
maps a fully-qualified Python symbol to a compiler behavior (`treat-as`) and
optionally extracts parameter values into AsyncActor manifest fields via a
`where:` tree.

Source: `src/asya-lab/asya_lab/compiler/rules.py`,
`src/asya-lab/asya_lab/compiler/extractor.py`

---

## Design principles

### Explicit over implicit

The rules file is the single source of truth for how the compiler interprets
Python constructs. There is no hardcoded behavior inside the compiler for any
specific library — tenacity, asyncio, stamina are all handled through the same
rule mechanism that users extend. If a rule is not declared, the construct is
not recognized.

This means you can always answer "what does the compiler do with `@retry`?" by
reading the YAML:

```yaml
- match: "tenacity.retry"
  treat-as: config
  where:
  - param: stop
    ...
```

No source diving, no special cases, no hidden logic.

### User-accessible configuration

Rules live in `.asya/config.compiler.rules.yaml` — a file delivered to the user
via `asya init`, checked into their project, and fully under their control. The
compiler's knowledge base is not locked inside a package; it is a project
artifact that users read, modify, and version alongside their flow code.

Shipped defaults extend automatically (users do not need to copy them), but
they can be inspected at any time in
`src/asya-lab/asya_lab/defaults/compiler.rules.yaml` and overridden per-project
by declaring a rule with the same `match` key.

### Pure syntactic mapping

Rules operate on AST nodes, not runtime values. The extractor reads literal
constants, names, and operator trees directly from the Python syntax tree.
There is no import execution, no decorator invocation, no side effects during
compilation. The mapping from Python construct to manifest field is a static,
deterministic transformation.

### Scope auto-detection

The parser infers scope from Python syntax — no `scope:` field in rules:

- `with foo():` = context manager (applies to all actors in the body)
- `@foo(...)` = decorator (applies to the decorated function)
- `p = foo(p)` = call-site

The rule author declares *what* to match and *what* to extract. The compiler
determines *where* the construct appears.

---

## Rule schema

Each rule is a YAML dict with the following fields:

```yaml
- match: "tenacity.retry"          # required: FQN of Python symbol
  treat-as: config                 # required (unless where: is present, then defaults to config)
  where:                           # optional: extraction tree
  - param: stop                    #   navigate into this parameter
    flatten-on: "|"                #   flatten BinOp before recursing
    where:                         #   child extraction nodes
    - match: "stop_after_attempt"  #   discriminator: only recurse if call matches
      where:
      - param: max_attempt_number
        assign-to: spec.resiliency.policies.default.maxAttempts  # terminal: extract value
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `match` | string | yes | Fully-qualified symbol name (e.g. `asyncio.timeout`, `tenacity.retry`). Matching is **exact** — no wildcards or patterns. |
| `treat-as` | string | yes* | One of: `actor`, `inline`, `unfold`, `flow`, `config`. *Defaults to `config` when `where:` is present. |
| `where` | list[WhereNode] | no | Extraction tree for pulling values from call arguments. |

---

## TreatAs values

Every function call in a flow is classified into one of five behaviors:

| Value | Effect | Use case |
|-------|--------|----------|
| `actor` | Separate K8s deployment with its own queue | Business logic handlers |
| `flow` | Sub-flow — compile recursively, create visual group in graph | Reusable flow compositions |
| `unfold` | Expand function body into current flow (no visual group) | Local helper functions |
| `inline` | Paste code into router body — runs inside the router process | Fast local transformations |
| `config` | Extract values into manifest, strip decorator/context manager at runtime | Resiliency, timeouts, library-specific config |

### Classification priority

When the compiler encounters a symbol, it resolves classification in this order
(highest to lowest priority):

1. **Inline comment** — `# asya: <action>` on the statement
2. **Definition-site decorator** — `@actor`, `@flow`, `@inline`, `@unfold` on the function definition
3. **Call-site wrapper** — `actor(fn)(p)`, `inline(fn)(p)`
4. **Compiler rule** — exact-match rules from `.asya/config.compiler.rules.yaml` + shipped defaults
5. **Implicit defaults** — local function = `unfold`, imported = `inline`, bare name = `actor`

---

## WhereNode specification

The `where:` tree guides value extraction from AST call nodes. Each node in the
tree is a `WhereNode` with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `param` | string, int, or ParamSpec | Parameter to navigate into. String = keyword name, int = positional index, dict = ParamSpec (see below). |
| `match` | string | Discriminator — only recurse into this node if the current call's function name equals this value. Used for polymorphic parameters (e.g. `stop=stop_after_attempt(...)` vs `stop=stop_after_delay(...)`). |
| `assign-to` | string | Terminal — extract the parameter value and write it to this spec path in the AsyncActor manifest. |
| `flatten-on` | string | Before recursing into children, flatten a BinOp tree using this operator. Supported: `"\|"` (BitOr), `"&"` (BitAnd), `"+"` (Add). |
| `access` | list[string] | Field access chain for navigating into nested attributes (reserved for future use). |
| `example` | string | Documentation string (not used by the engine). |
| `where` | list[WhereNode] | Child extraction nodes — recurse after navigating into `param`. |

### Node types

The where-tree walker recognizes three node patterns:

**Terminal node** (`param` + `assign-to`, no `where`):

Extract the literal value from the bound argument and store it at the spec path.

```yaml
- param: delay
  assign-to: spec.resiliency.timeout.actor
```

Given `asyncio.timeout(30)`, extracts `30` and writes
`spec.resiliency.timeout.actor: 30`.

**Non-terminal node** (`param` + `where`):

The bound argument is itself a call. Bind its arguments and recurse into
children.

```yaml
- param: stop
  where:
  - match: "stop_after_attempt"
    where:
    - param: max_attempt_number
      assign-to: spec.resiliency.policies.default.maxAttempts
```

Given `retry(stop=stop_after_attempt(3))`, navigates into the `stop` argument,
finds `stop_after_attempt(3)`, binds `max_attempt_number=3`, extracts `3`.

**Match-only node** (`match` + `where`, no `param`):

Discriminator — only recurse if the current call's function name matches. Used
when a parameter can hold different function calls (polymorphic dispatch).

```yaml
- param: wait
  where:
  - match: "wait_exponential"     # only if wait=wait_exponential(...)
    where:
    - param: min
      assign-to: spec.resiliency.policies.default.initialDelay
  - match: "wait_fixed"           # only if wait=wait_fixed(...)
    where:
    - param: wait
      assign-to: spec.resiliency.policies.default.initialDelay
```

---

## ParamSpec

For parameters that can be passed both positionally and as keywords, rules can
declare a `ParamSpec` dict instead of a plain string:

```yaml
param: {arg: 0, kwarg: "delay", type: "int"}
```

| Field | Type | Description |
|-------|------|-------------|
| `arg` | int | Positional argument index (0-based) |
| `kwarg` | string | Keyword argument name |
| `type` | string | Optional type annotation (metadata, not enforced) |

Resolution order: try `kwarg` first (always known from keyword arguments), then
fall back to positional `arg` index.

This handles functions where the same parameter can be passed either way:

```python
asyncio.timeout(30)          # positional: arg=0
asyncio.timeout(delay=30)    # keyword: kwarg="delay"
```

When `param` is a plain string, only keyword matching is used. When `param` is
an integer, only positional matching is used.

---

## BinOp flattening

When a parameter's value is a binary operation (e.g.
`stop_after_attempt(5) | stop_after_delay(30)`), the `flatten-on` field
instructs the extractor to flatten the expression tree into a list of calls
before matching children.

```yaml
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

Given `stop=stop_after_attempt(5) | stop_after_delay(30)`:

1. The extractor sees a `BinOp` with `BitOr` operator
2. Flattens into `[stop_after_attempt(5), stop_after_delay(30)]`
3. Each call is matched against the `match:` discriminators independently
4. Result: `{maxAttempts: 5, maxDuration: 30}`

Without `flatten-on`, BinOp expressions are not traversed.

Supported operators:

| `flatten-on` | Python operator | AST type |
|--------------|-----------------|----------|
| `"\|"` | `\|` (bitwise OR) | `ast.BitOr` |
| `"&"` | `&` (bitwise AND) | `ast.BitAnd` |
| `"+"` | `+` (addition) | `ast.Add` |

---

## Value extraction

The extractor handles these AST expression types when resolving terminal
`assign-to` nodes:

| AST type | Python example | Extracted value |
|----------|----------------|-----------------|
| `ast.Constant` | `30`, `"hello"`, `True` | Literal value (int, float, str, bool) |
| `ast.Name` | `ValueError` | Identifier as string |
| `ast.Tuple` | `(ValueError, TypeError)` | Comma-joined string |
| `ast.UnaryOp(USub)` | `-5` | Negated number |
| Complex expressions | `foo()`, `x + y` | `None` (not extractable — silently skipped) |

---

## Argument binding

The extractor first binds call arguments to parameter names, then rules look
up values from the resulting map.

**Binding** (call arguments to names):

1. **Keywords** — arguments passed with a keyword (e.g. `func(delay=30)`) are
   bound directly to their name (`delay`)
2. **Positional + `inspect.signature`** — for positional arguments, the
   extractor imports the called function at compile time and uses its signature
   to map arguments to parameter names
3. **Positional fallback** — if introspection fails (e.g. the function cannot
   be imported), positional arguments are bound using their 0-based index as a
   string key (`"0"`, `"1"`, ...)

The import map from the flow file's `import` statements resolves bare names to
FQNs (e.g. `stop_after_attempt` to `tenacity.stop_after_attempt`) for
`inspect.signature` lookups.

**Lookup** (rule navigates the bound map):

After binding, rules use `param` to look up values. A plain string looks up by
keyword name, an integer by positional index, and a `ParamSpec` tries keyword
first then falls back to positional index (see [ParamSpec](#paramspec)).

---

## Where rules apply: flows vs actor definitions

Rules operate in two distinct contexts within the same compilation. The
compiler auto-detects which context applies from Python syntax.

### Context managers in flow bodies

When a `with` statement appears inside the flow function, the compiler:

1. Matches the context manager symbol against rules
2. Strips the `with` block from generated routers (no trace in compiled output)
3. Extracts config values via the where-tree
4. Injects extracted values into manifests for **all actors inside the scope**

```python
async with asyncio.timeout(30):    # scope covers both actors below
    p = ocr_extractor(p)           # gets spec.resiliency.timeout.actor: 30
    p = language_detector(p)       # gets spec.resiliency.timeout.actor: 30
p = sentiment_analyzer(p)         # outside scope — no timeout injected
```

The extracted config record includes scope metadata:

```python
{
    "symbol": "asyncio.timeout",
    "spec_values": {"spec.resiliency.timeout.actor": 30},
    "scope_type": "context_manager",
    "scope_actors": ["ocr_extractor", "language_detector"],
}
```

Nested scopes are tracked independently — each `with` block produces a separate
config record with its own `scope_actors` list.

See [`flow_with_asyncio_timeout.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/resiliency/flows/flow_with_asyncio_timeout.py)
in [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) for a full walkthrough.

### Decorators on actor definitions

When a decorator appears on a function definition (in the same file or an
imported module), the compiler:

1. Matches the decorator symbol against rules
2. Extracts config values via the where-tree
3. Injects extracted values into the manifest for **that single actor**
4. Adds the decorator FQN to `ASYA_IGNORE_DECORATORS` env var in the manifest

```python
@retry(stop=stop_after_attempt(5))   # extracted for fetch_data only
def fetch_data(p: dict) -> dict: ... # gets maxAttempts: 5 + ASYA_IGNORE_DECORATORS
```

The extracted config record includes scope metadata:

```python
{
    "symbol": "tenacity.retry",
    "spec_values": {"spec.resiliency.policies.default.maxAttempts": 5},
    "scope_type": "decorator",
    "scope_actors": ["fetch_data"],
}
```

The `ASYA_IGNORE_DECORATORS` env var tells asya-runtime to strip the decorator
before loading the handler module, so `@retry(...)` does not execute at runtime.

See [`flow_decorator_retry.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/compiler-sugar/flows/flow_decorator_retry.py)
in [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) for a full walkthrough.

### Rule-matched vs unknown decorators

The compiler **only strips decorators that match a rule**. This is a core design
principle: the rules file is the knowledge base for what the compiler understands.

- **Rule-matched decorators** (e.g. `tenacity.retry` with `treat-as: config`) are
  stripped at runtime via `ASYA_IGNORE_DECORATORS`. Their behavior is implemented
  by the Asya platform (sidecar retry policies, Crossplane manifest fields), so
  running them in Python would be redundant or conflicting.

- **Unknown decorators** (no rule match) are **never stripped**. They are user
  business logic — logging, auth, caching, validation — and must execute at
  runtime. The compiler passes them through unchanged. The `# asya: actor`
  directive and `@actor` decorator classify the function as an actor, but they
  do not affect other decorators on the same function.

```python
@some_logging_decorator       # unknown — preserved, runs at runtime
@retry(stop=stop_after_attempt(3))  # rule-matched — stripped, config extracted
async def handler(p: dict) -> dict:  # asya: actor
    ...
```

In the generated manifest, `@retry` params appear as `spec.resiliency.policies`,
and `@some_logging_decorator` remains on the handler at runtime.

### Both mechanisms in one flow

Context managers and decorators can work together on the same flow. The
templater applies scope configs first (context managers), then decorator configs.
Decorator configs are more specific and override scope values for the same
spec path.

```python
@flow
async def resilient_pipeline(p: dict) -> dict:
    async with asyncio.timeout(30):        # scope: fetch_data, transform_data
        p = await fetch_data(p)            # timeout: 30 + maxAttempts: 5
        p = await transform_data(p)        # timeout: 30
    p = await store_results(p)             # no extracted config
    return p

@actor
@retry(stop=stop_after_attempt(5))
def fetch_data(p: dict) -> dict: ...
```

### Inline comment overrides

The `# asya: <action>` comment on any flow statement overrides all rules and
defaults. Supported actions: `actor`, `inline`, `unfold`, `flow`, `config`.

```python
p = normalize(p)  # asya: inline    — force inline, no actor boundary
p = validate(p)   # asya: actor     — force separate actor
```

See [`flow_inline_comment_overrides.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/compiler-sugar/flows/flow_inline_comment_overrides.py)
in [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) for a working example.

---

## Rule loading and precedence

Rules are loaded from two sources:

1. **Shipped defaults** — `src/asya-lab/asya_lab/defaults/compiler.rules.yaml`
2. **User rules** — `.asya/config.compiler.rules.yaml` (created by `asya init`)

User rules **extend** (not replace) defaults. When both define a rule for the
same `match` key, the user rule takes precedence (overwrites the default).

Loading order in `RuleEngine.with_defaults()`:

```
defaults = load("defaults/compiler.rules.yaml")
rules = defaults + user_rules
engine = RuleEngine(rules)  # dict keyed by match → last write wins
```

---

## Shipped default rules

Seven rules ship with asya-lab:

| Rule | Symbol | TreatAs | Effect |
|------|--------|---------|--------|
| asyncio.timeout | `asyncio.timeout` | `config` | Extracts `spec.resiliency.timeout.actor` |
| tenacity.retry | `tenacity.retry` | `config` | Extracts `maxAttempts`, `maxDuration`, `initialDelay`, `maxInterval` |
| timeout_decorator | `timeout_decorator.timeout` | `config` | Extracts `spec.resiliency.timeout.actor` |
| stamina.retry | `stamina.retry` | `config` | Extracts `maxAttempts`, `maxDuration` |
| claude_agent_sdk.tool | `claude_agent_sdk.tool` | `actor` | Classifies as actor, generates adapter if non-standard signature |
| langchain.tools.tool | `langchain.tools.tool` | `actor` | Classifies as actor, generates adapter if non-standard signature |
| langchain_core.tools.tool | `langchain_core.tools.tool` | `actor` | Classifies as actor, generates adapter if non-standard signature |

The `config` rules extract parameter values into manifest fields. The `actor`
rules classify decorated functions as actors and strip the decorator at runtime
via `ASYA_IGNORE_DECORATORS`. When actor-classified functions use non-standard
call patterns (e.g. `p["result"] = fn(p["city"])` instead of `p = fn(p)`), the
compiler generates an **adapter file** — see [Adapter generation](#adapter-generation).

See the full YAML in
`src/asya-lab/asya_lab/defaults/compiler.rules.yaml`.

---

## Adapter generation

When a function classified as `actor` (via rule, decorator, or `# asya: actor`
directive) is called with a non-standard pattern, the compiler generates an
adapter wrapper that bridges the function's typed signature to Asya's
`dict -> dict` envelope protocol.

### Standard vs non-standard calls

**Standard call** — no adapter needed:

```python
p = handler(p)           # ActorCall: dict -> dict, deployed directly
```

**Non-standard call** — adapter generated:

```python
p["weather"] = get_weather(p["city"])           # AdapterCall: typed args + subscript target
p["greeting"] = format_greeting(p["user_name"]) # AdapterCall: typed args + subscript target
```

### Generated adapter file

For `p["weather"] = await get_weather(p["city"])`, the compiler produces
`adapter_get_weather.py`:

```python
"""Auto-generated adapter for get_weather"""
from module import get_weather                # added when function is imported

async def adapter_get_weather(payload: dict):
    """Adapter: wraps get_weather() for dict-in/dict-out protocol"""
    _result = await get_weather(payload["city"])
    payload["weather"] = _result
    yield payload
```

Key properties:
- **Argument denormalization**: internal `p["key"]` references are expanded to
  `payload["key"]` in the adapter
- **Import injection**: when the function is imported from another module, the
  adapter includes the appropriate `from module import func` statement (with
  `as alias` when the local name differs from the original)
- **Async preservation**: async functions get `async def` + `await`; sync
  functions get plain `def`
- **Output routing**: subscript targets (`p["key"] = ...`) store the result at
  that key; bare assignment (`p = fn(...)`) replaces the entire payload

### Deployment

The adapter file is deployed as a ConfigMap alongside the actor's handler code.
At runtime, the adapter function is loaded as the actor's handler instead of the
original function. The adapter calls the original function, wrapping its inputs
and outputs for the envelope protocol.

### Example

See [`flow_tool_adapter.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/compiler-sugar/flows/flow_tool_adapter.py)
in [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo).

---

## See also

- [Compiler Rules Guide](../../usage/guide-compiler-rules.md) — practical guide
  with step-by-step examples
- [Flow DSL Reference](flow-dsl.md) — flow syntax, symbol classification,
  value extractor details
- [Flow Compiler Architecture](../components/lab-flow-compiler.md) — compiler
  internals, pipeline stages
- [AsyncActor CRD Reference](asyncactor-crd.md) — manifest field paths
  used in `assign-to`
