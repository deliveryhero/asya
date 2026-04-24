---
description: "Compiler rules usage: extend compiler with custom rules for decorators, context managers, calls"
---

# Compiler Rules

How to use and extend the compiler's extensible rule system — the knowledge base
that teaches the flow compiler how to interpret Python decorators, context
managers, and function calls.

For the formal specification, see
[reference/specs/compiler-rules.md](../reference/specs/compiler-rules.md).

---

## What are compiler rules?

When the flow compiler encounters a Python construct like `@retry(...)` or
`with asyncio.timeout(30):`, it needs to know what to do with it. Should it
become a separate actor? Should the compiler extract configuration from it?
Should it be inlined into the router?

Compiler rules answer these questions. Each rule maps a Python symbol to a
compiler behavior and optionally tells the compiler how to extract parameter
values into AsyncActor manifest fields.

### Explicit over implicit

The central design principle: **the rules file is the single source of truth**.
There is no hardcoded behavior for any specific library inside the compiler.
Tenacity, asyncio, stamina — all handled through the same rule mechanism that
you extend for your own project.

If you want to know what the compiler does with `@retry(...)`, read the YAML:

```yaml
- match: "tenacity.retry"
  treat-as: config
  where:
  - param: stop
    ...
```

No source diving required. No hidden magic.

### User-accessible configuration

Rules live in `.asya/config.compiler.rules.yaml` — a file delivered to you via
`asya init`, checked into your project, fully under your control. The
compiler's knowledge base is not locked inside a package; it is a project
artifact you read, modify, and version alongside your flow code.

**Why the long filename?** Asya uses a filename-to-key convention: dotted parts
in the filename become nested config keys. `config.compiler.rules.yaml`
automatically maps to `compiler.rules` in the merged config tree. This means
you can also define rules inside `config.yaml` under `compiler.rules:` — both
sources are merged (extended, not replaced).

**Subdirectory merging.** Asya walks up from the current directory to the git
root, collecting all `.asya/` directories it finds. Config files are merged
root-first, nearest-wins. Lists (like rules) are **extended** across
directories, so a subdirectory's rules add to the parent's rules rather than
replacing them:

```
project/
  .asya/config.compiler.rules.yaml      # 2 rules (root)
  pipelines/
    .asya/config.compiler.rules.yaml    # 1 rule (subdirectory)
```

Compiling from `pipelines/` sees all 3 rules. Compiling from `project/` sees
only the root 2.

### Pure syntactic mapping

Rules operate on AST structure, not runtime values.
`@retry(stop=stop_after_attempt(3))` is matched and extracted at compile time;
`3` is a literal the compiler reads directly from the syntax tree. No decorator
invocation, no imports executed, no side effects.

---

## Getting started

Rules are created automatically when you initialize a project:

```bash
asya init --registry ghcr.io/my-org
```

This creates `.asya/config.compiler.rules.yaml` with the shipped defaults as
annotated examples. The file is ready to extend.

---

## Where rules apply: flows vs actors

Rules operate in two contexts. The same rule YAML works in both — the compiler
auto-detects scope from Python syntax.

### Context managers in flows

Context managers appear inside the flow function body. The compiler strips the
`with` block and injects extracted config into every actor within the scope.

Source: [`flow_with_asyncio_timeout.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/resiliency/flows/flow_with_asyncio_timeout.py)

```python
@flow
async def document_pipeline(p: dict) -> dict:
    p["status"] = "processing"

    async with asyncio.timeout(30):
        p = ocr_extractor(p)
        p = language_detector(p)

    if p.get("language") != "en":
        p = translator(p)

    p = sentiment_analyzer(p)
    p["status"] = "done"
    return p
```

The compiler:
1. Strips `async with asyncio.timeout(30):` from the generated routers
2. Extracts `30` via the `asyncio.timeout` rule's where-tree
3. Writes `spec.resiliency.timeout.actor: 30` into the manifests for
   `ocr_extractor` and `language_detector` (the actors inside the scope)
4. Leaves `translator` and `sentiment_analyzer` unaffected (outside the scope)

The generated router has no trace of the timeout — it is pure routing logic:

Compiled output: [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) (generated from the source above)

```python
async def start_document_pipeline(payload: dict):
    p = payload
    _next = []
    p['status'] = 'processing'
    _next.append(resolve("ocr_extractor"))
    _next.append(resolve("language_detector"))
    _next.append(resolve("router_document_pipeline_line_23_if_2"))
    yield "SET", ".route.next[:0]", _next
    yield payload
```

Nested scopes are supported — each tracks its own actors independently.

Source: [`flow_with_nested_timeout_scopes.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/resiliency/flows/flow_with_nested_timeout_scopes.py)

```python
@flow
async def ingestion_pipeline(p: dict) -> dict:
    async with asyncio.timeout(60):        # scope: fetch, parse, validate
        p = data_fetcher(p)
        async with asyncio.timeout(10):    # scope: parse, validate only
            p = data_parser(p)
            p = data_validator(p)
    p = data_writer(p)                     # no timeout scope
    return p
```

### Decorators on actor definitions

Decorators appear on handler function definitions — either in the same file as
the flow or in imported modules. The compiler extracts config from the decorator
arguments and applies it to that single actor's manifest.

Source: [`flow_decorator_retry.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/compiler-sugar/flows/flow_decorator_retry.py)

```python
import asyncio
from tenacity import retry, stop_after_attempt

@flow
async def resilient_pipeline(p: dict) -> dict:
    p["status"] = "processing"

    async with asyncio.timeout(30):
        p = await fetch_data(p)
        p = await transform_data(p)

    p = await store_results(p)
    return p


@actor
@retry(stop=stop_after_attempt(5))
def fetch_data(p: dict) -> dict:
    """Fetch data from external API — retries up to 5 times on failure."""
    p["data"] = "fetched"
    return p


@actor
def transform_data(p: dict) -> dict:
    """Transform fetched data."""
    p["transformed"] = True
    return p


@actor
def store_results(p: dict) -> dict:
    """Store final results."""
    p["stored"] = True
    return p
```

Here both mechanisms work together on the same flow:

| Actor | Context manager scope | Decorator | Manifest result |
|-------|----------------------|-----------|-----------------|
| `fetch_data` | `asyncio.timeout(30)` | `@retry(stop=stop_after_attempt(5))` | `timeout.actor: 30` + `maxAttempts: 5` + `ASYA_IGNORE_DECORATORS=tenacity.retry` |
| `transform_data` | `asyncio.timeout(30)` | (none) | `timeout.actor: 30` |
| `store_results` | (outside scope) | (none) | (no extracted config) |

The compiler:
1. Scans `@retry(stop=stop_after_attempt(5))` on `fetch_data`
2. Resolves `retry` to `tenacity.retry` via the import map
3. Walks the where-tree: `param: stop` -> `match: stop_after_attempt` -> `param: max_attempt_number` -> `assign-to: spec.resiliency.policies.default.maxAttempts`
4. Extracts `5` and stores it for `fetch_data`'s manifest
5. Adds `tenacity.retry` to `ASYA_IGNORE_DECORATORS` so the runtime strips `@retry` before loading the handler

Compiled output: [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) (generated from the source above)

### Inline overrides on flow statements

For per-call control without rules, use `# asya: <action>` comments directly
on flow statements.

Source: [`flow_inline_comment_overrides.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/compiler-sugar/flows/flow_inline_comment_overrides.py)

```python
@flow
def order_pipeline(p: dict) -> dict:
    p = normalize_keys(p)  # asya: inline   — runs inside the router process
    p = validate_order(p)  # asya: actor    — separate actor with its own queue

    if p.get("fraud_score", 0) > 0.8:
        p["status"] = "rejected"
        return p

    p = charge_payment(p)
    return p
```

Compiled output: [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) (generated from the source above)

In the generated router, `normalize_keys` is inlined (its code runs inside the
router function), while `validate_order` and `charge_payment` are resolved as
separate actors via `resolve()`.

### Definition-site decorators

Functions decorated with `@actor`, `@inline`, `@flow`, or `@unfold` at their
definition site carry that classification everywhere they are called.

Source: [`examples/flows/08_decorators.py`](../../examples/flows/08_decorators.py)

```python
@inline
def inject_trace(p: dict) -> dict:
    """Runs inside the router — no actor boundary."""
    p.setdefault("trace_id", str(uuid.uuid4()))
    return p

@actor
def validate(p: dict) -> dict:
    """Deployed as a separate actor."""
    if "id" not in p:
        raise ValueError("missing required field: id")
    return p
```

And the equivalent call-site pattern for functions defined elsewhere:

Source: [`flow_decorator_callsite.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/compiler-sugar/flows/flow_decorator_callsite.py)

```python
p = inline(stamp_timestamp)(p)  # force inline regardless of definition
p = actor(validator)(p)          # force actor regardless of definition
```

---

## Built-in rules

Seven rules ship with asya-lab and apply automatically (no configuration needed).
See the full YAML in
[`src/asya-lab/asya_lab/defaults/compiler.rules.yaml`](../../src/asya-lab/asya_lab/defaults/compiler.rules.yaml).

### Tool decorator rules (claude_agent_sdk.tool, langchain.tools.tool, langchain_core.tools.tool)

Functions decorated with `@tool` from supported frameworks are classified as
actors. When called with non-standard signatures, the compiler generates an
adapter wrapper.

Source: [`flow_tool_adapter.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/compiler-sugar/flows/flow_tool_adapter.py)

```python
from claude_agent_sdk import tool

@tool
async def get_weather(city: str) -> dict:
    """Get current weather for a city."""
    return {"temp": 22, "condition": "sunny"}

@tool
def format_greeting(name: str) -> str:
    """Format a personalized greeting."""
    return f"Hello, {name}!"

@flow
async def tool_adapter(p: dict) -> dict:
    p = await validate_input(p)
    p["weather"] = await get_weather(p["city"])        # adapter generated
    p["greeting"] = format_greeting(p["user_name"])    # adapter generated
    p = await compose_response(p)
    return p
```

The compiler:
1. Resolves `tool` to `claude_agent_sdk.tool` via the import map
2. Classifies `get_weather` and `format_greeting` as actors (treat-as: actor)
3. Detects non-standard call patterns (`p["weather"] = get_weather(p["city"])`)
4. Generates adapter files: `adapter_get_weather.py` and `adapter_format_greeting.py`
5. Adds `claude_agent_sdk.tool` to `ASYA_IGNORE_DECORATORS` so the runtime strips `@tool`

Generated adapter (`adapter_get_weather.py`):

```python
async def adapter_get_weather(payload: dict):
    """Adapter: wraps get_weather() for dict-in/dict-out protocol"""
    _result = await get_weather(payload["city"])
    payload["weather"] = _result
    yield payload
```

Standard `p = fn(p)` calls with `@tool` are treated as regular actor calls
(no adapter needed). The adapter is only generated for non-standard patterns.

Compiled output: [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) (generated from the source above)

### asyncio.timeout

```python
async with asyncio.timeout(30):
    p = ocr_extractor(p)
```

Extracts `30` into `spec.resiliency.timeout.actor` for all actors in scope.

### tenacity.retry

```python
@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=1, max=60))
def fetch_data(p: dict) -> dict: ...
```

Extracts into the manifest:
- `spec.resiliency.policies.default.maxAttempts: 5`
- `spec.resiliency.policies.default.initialDelay: 1`
- `spec.resiliency.policies.default.maxInterval: 60`

Also handles combined stop conditions with `|`:

```python
@retry(stop=stop_after_attempt(5) | stop_after_delay(30))
def fetch_data(p: dict) -> dict: ...
```

Extracts both `maxAttempts: 5` and `maxDuration: 30`.

### timeout_decorator.timeout

```python
@timeout(30)
def slow_handler(p: dict) -> dict: ...
```

Extracts `30` into `spec.resiliency.timeout.actor`.

### stamina.retry

```python
@stamina.retry(attempts=3, timeout=60)
def resilient_handler(p: dict) -> dict: ...
```

Extracts `maxAttempts: 3` and `maxDuration: 60`.

---

## Writing custom rules

Add rules to `.asya/config.compiler.rules.yaml`. User rules extend shipped
defaults — they do not replace them.

### Simple decorator extraction

Map a custom timeout decorator to a manifest field:

```yaml
# @my_timeout(seconds=30) -> spec.resiliency.actorTimeout: 30
- match: "mylib.my_timeout"
  treat-as: config
  where:
  - param: seconds
    assign-to: spec.resiliency.actorTimeout
```

Given:

```python
from mylib import my_timeout

@my_timeout(seconds=30)
def slow_handler(p: dict) -> dict: ...
```

The compiler extracts `30` and writes `spec.resiliency.actorTimeout: 30` to the
actor's manifest. The `@my_timeout` decorator is stripped at runtime via
`ASYA_IGNORE_DECORATORS`.

### Nested extraction with where-trees

For decorators with nested function calls as arguments, use a `where:` tree to
navigate into the call structure. The built-in `tenacity.retry` rule is the
canonical example:

```yaml
- match: "mylib.retry"
  treat-as: config
  where:
  - param: attempts
    assign-to: spec.resiliency.policies.default.maxAttempts
  - param: backoff
    where:
    - match: "exponential"
      where:
      - param: base
        assign-to: spec.resiliency.policies.default.initialDelay
      - param: cap
        assign-to: spec.resiliency.policies.default.maxInterval
```

This handles:

```python
@retry(attempts=5, backoff=exponential(base=1, cap=60))
def fragile_service(p: dict) -> dict: ...
```

Result: `{maxAttempts: 5, initialDelay: 1, maxInterval: 60}`.

### Handling operator-combined arguments

Some libraries combine parameters with `|`, `&`, or `+` operators. Use
`flatten-on` to flatten the expression tree before matching. This is how the
built-in `tenacity.retry` rule handles combined stop conditions:

```yaml
- match: "mylib.retry"
  treat-as: config
  where:
  - param: stop
    flatten-on: "|"
    where:
    - match: "after_attempts"
      where:
      - param: n
        assign-to: spec.resiliency.policies.default.maxAttempts
    - match: "after_delay"
      where:
      - param: seconds
        assign-to: spec.resiliency.policies.default.maxDuration
```

This handles:

```python
@retry(stop=after_attempts(5) | after_delay(30))
def api_call(p: dict) -> dict: ...
```

### Context manager rules

Context manager rules work the same way — the parser auto-detects that a `with`
statement triggers the rule. The built-in `asyncio.timeout` rule is the
canonical example:

```yaml
- match: "mylib.deadline"
  treat-as: config
  where:
  - param: seconds
    assign-to: spec.resiliency.actorTimeout
```

```python
async with mylib.deadline(seconds=30):
    p = process(p)
    p = validate(p)
```

Both `process` and `validate` get `spec.resiliency.actorTimeout: 30` in
their manifests.

---

## How it works end-to-end

Here is the full pipeline for a `@retry` decorator:

```
1. Parser encounters @retry(stop=stop_after_attempt(5)) on def fetch_data
2. Import map resolves "retry" -> "tenacity.retry"
3. RuleEngine.classify("tenacity.retry") -> TreatAs.CONFIG
4. RuleEngine.get_rule("tenacity.retry") -> CompilerRule with where: tree
5. ValueExtractor.extract(ast_call_node, rule) walks the where: tree:
   a. Bind args: stop=stop_after_attempt(5)
   b. Navigate into "stop" param -> find ast.Call(stop_after_attempt, args=[5])
   c. Match discriminator "stop_after_attempt" -> match
   d. Bind args: max_attempt_number=5
   e. Terminal: assign-to spec.resiliency.policies.default.maxAttempts = 5
6. Parser stores extracted_values: {"spec.resiliency.policies.default.maxAttempts": 5}
7. Parser adds "tenacity.retry" to ignore_decorators list
8. Templater writes maxAttempts: 5 into the AsyncActor manifest
9. Templater writes ASYA_IGNORE_DECORATORS=tenacity.retry into the manifest env
10. At runtime, asya-runtime strips @retry before loading the handler module
```

---

## Scope semantics

The parser auto-detects scope from Python syntax:

| Syntax | Scope | Applies to |
|--------|-------|------------|
| `with foo():` | Context manager | All actors inside the `with` body |
| `@foo(...)` | Decorator | The decorated function only |
| `p = foo(p)` | Call-site | The call itself |

### Nested context manager scopes

Each `with` block tracks its own set of actors:

```python
async with asyncio.timeout(60):        # scope: fetch, parse, validate
    p = fetch(p)
    async with asyncio.timeout(10):    # scope: parse, validate only
        p = parse(p)
        p = validate(p)
p = store(p)                           # no timeout scope
```

The compiler understands nested scopes. In this example:
- A 60s timeout applies to the group of actors: `fetch`, `parse`, and `validate`
- A nested, more restrictive 10s timeout applies to the subgroup containing only `parse` and `validate`
- The `store` actor is outside of any timeout scope defined here

---

## Rule matching

Matching is **exact** — the rule's `match` field must equal the fully-qualified
symbol name. No wildcards, no regex, no pattern matching.

The compiler resolves bare names to FQNs using the flow file's import
statements:

```python
from tenacity import retry    # "retry" resolves to "tenacity.retry"
import asyncio                # "asyncio.timeout" stays as-is
```

If a symbol cannot be resolved to an FQN, matching uses the bare name.

---

## Examples

The [`examples/flows/`](../../examples/flows/) directory contains teaser examples.
Comprehensive working examples with compiled output are in
[examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo).

| Source file | Compiled output | Demonstrates |
|-------------|-----------------|--------------|
| [`flow_decorator_retry.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/compiler-sugar/flows/flow_decorator_retry.py) | [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) | `@retry` config extraction + `asyncio.timeout` scope |
| [`flow_with_asyncio_timeout.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/resiliency/flows/flow_with_asyncio_timeout.py) | [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) | Context manager scoped to multiple actors |
| [`flow_with_nested_timeout_scopes.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/resiliency/flows/flow_with_nested_timeout_scopes.py) | [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) | Nested scopes with different timeouts |
| [`08_decorators.py`](../../examples/flows/08_decorators.py) | (compile locally) | `@actor` and `@inline` on function definitions |
| [`flow_decorator_callsite.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/compiler-sugar/flows/flow_decorator_callsite.py) | [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) | `actor(fn)(p)` and `inline(fn)(p)` wrappers |
| [`flow_inline_comment_overrides.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/compiler-sugar/flows/flow_inline_comment_overrides.py) | [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) | `# asya: actor` / `# asya: inline` directives |
| [`flow_tool_adapter.py`](https://github.com/asyacore/asya/blob/main/examples/end-to-end/monorepo/src/compiler-sugar/flows/flow_tool_adapter.py) | [examples/end-to-end/monorepo](https://github.com/asyacore/asya/tree/main/examples/end-to-end/monorepo) | `@tool` adapter generation for non-standard signatures |

Compile any example yourself:

```bash
asya flow compile examples/flows/08_decorators.py --plot
```

---

## See also

- [Compiler Rules Specification](../reference/specs/compiler-rules.md) — formal
  schema, WhereNode fields, ParamSpec, value extraction rules
- [Flow DSL Reference](../reference/specs/flow-dsl.md) — flow syntax and
  symbol classification
- [Flow Compiler Architecture](../reference/components/lab-flow-compiler.md) —
  compiler pipeline and internals
- [Timeouts Guide](guide-timeouts.md) — setting actor timeouts
- [Error Handling Guide](guide-error-handling.md) — try/except in flows,
  resiliency policies
