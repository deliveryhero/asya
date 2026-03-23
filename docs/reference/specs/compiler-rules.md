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

The design principles:

- **Pure syntactic mapping** — rules operate on AST nodes, not runtime values.
  No hidden magic; every extraction is declared in YAML.
- **Extensible knowledge base** — shipped defaults cover common libraries
  (tenacity, asyncio, stamina). Users add project-specific rules without
  modifying compiler code.
- **Scope auto-detection** — the parser infers scope from Python syntax
  (`with` = context manager, `@` = decorator, `p = call(p)` = call-site).
  No `scope:` field in rules.

Source: `src/asya-lab/asya_lab/compiler/rules.py`,
`src/asya-lab/asya_lab/compiler/extractor.py`

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

The extractor binds call arguments to parameter names using this resolution
chain:

1. **Keywords** — always known (`func(delay=30)` binds `delay` directly)
2. **Positional + `inspect.signature`** — the extractor imports the function at
   compile time and reads its signature to map positional args to parameter names
3. **Positional + ParamSpec** — rule declares both bindings explicitly
4. **Positional fallback** — positional index as string key (`"0"`, `"1"`, ...)

The import map from the flow file's `import` statements is used to resolve bare
names to FQNs (e.g. `stop_after_attempt` to `tenacity.stop_after_attempt`) for
`inspect.signature` lookups.

---

## Scope semantics

The parser auto-detects scope from Python syntax — no `scope:` field in rules:

| Python syntax | Scope | Config applies to |
|---------------|-------|-------------------|
| `with foo():` | Context manager | All actors in the `with` body |
| `@foo(...)` on `def fn` | Decorator | The decorated function only |
| `p = foo(p)` | Call-site | The call itself |

### Context manager scoping

Context managers can be nested. Each scope tracks its own actors:

```python
async with asyncio.timeout(60):     # scope: fetch, parse, validate
    p = fetch(p)
    async with asyncio.timeout(10): # scope: parse, validate only
        p = parse(p)
        p = validate(p)
```

The compiler emits separate extracted configs for each scope with their
respective `scope_actors` lists.

### Decorator stripping

Config rules with `treat-as: config` cause the matched decorator to be added
to the `ASYA_IGNORE_DECORATORS` environment variable in the generated manifest.
The asya-runtime reads this variable and strips matching decorators before
loading the handler module, so decorators like `@retry(...)` do not execute at
runtime.

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

Four rules ship with asya-lab:

| Rule | Symbol | Extracts to |
|------|--------|-------------|
| asyncio.timeout | `asyncio.timeout` | `spec.resiliency.timeout.actor` |
| tenacity.retry | `tenacity.retry` | `maxAttempts`, `maxDuration`, `initialDelay`, `maxInterval` |
| timeout_decorator | `timeout_decorator.timeout` | `spec.resiliency.timeout.actor` |
| stamina.retry | `stamina.retry` | `maxAttempts`, `maxDuration` |

See the full YAML in
`src/asya-lab/asya_lab/defaults/compiler.rules.yaml`.

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
