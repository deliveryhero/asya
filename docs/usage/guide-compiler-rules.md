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

The key design points:

- **No hidden magic** — every extraction is declared in YAML. You can read the
  rules file and know exactly what the compiler will do.
- **Pure syntactic mapping** — rules operate on AST structure, not runtime
  values. `@retry(stop=stop_after_attempt(3))` is matched and extracted at
  compile time; `3` is a literal the compiler reads from the syntax tree.
- **Extensible** — defaults cover common libraries. Add your own rules for
  project-specific decorators without touching compiler code.

---

## Getting started

Rules are created automatically when you initialize a project:

```bash
asya init --registry ghcr.io/my-org
```

This creates `.asya/config.compiler.rules.yaml` with the shipped defaults as
annotated examples. The file is ready to extend.

---

## Built-in rules

Four rules ship with asya-lab and apply automatically (no configuration needed):

### asyncio.timeout

```python
async with asyncio.timeout(30):
    p = ocr_extractor(p)
    p = language_detector(p)
```

Extracts `30` into `spec.resiliency.timeout.actor` for all actors in the scope
(both `ocr_extractor` and `language_detector`).

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

Map a custom decorator to a manifest field:

```yaml
# @rate_limit(qps=10) -> spec.scaling.rateLimit: 10
- match: "mylib.rate_limit"
  treat-as: config
  where:
  - param: qps
    assign-to: spec.scaling.rateLimit
```

Given:

```python
from mylib import rate_limit

@rate_limit(qps=10)
def api_handler(p: dict) -> dict: ...
```

The compiler extracts `10` and writes `spec.scaling.rateLimit: 10` to the
actor's manifest. The `@rate_limit` decorator is stripped at runtime via
`ASYA_IGNORE_DECORATORS`.

### Nested extraction with where-trees

For decorators with nested function calls as arguments, use a `where:` tree to
navigate into the call structure:

```yaml
- match: "mylib.circuit_breaker"
  treat-as: config
  where:
  - param: threshold
    assign-to: spec.resiliency.circuitBreaker.threshold
  - param: recovery
    where:
    - match: "exponential_backoff"
      where:
      - param: base
        assign-to: spec.resiliency.circuitBreaker.backoffBase
      - param: max_delay
        assign-to: spec.resiliency.circuitBreaker.backoffMax
```

This handles:

```python
@circuit_breaker(
    threshold=5,
    recovery=exponential_backoff(base=2, max_delay=120)
)
def fragile_service(p: dict) -> dict: ...
```

Result: `{threshold: 5, backoffBase: 2, backoffMax: 120}`.

### Handling operator-combined arguments

Some libraries combine parameters with `|`, `&`, or `+` operators. Use
`flatten-on` to flatten the expression tree before matching:

```yaml
- match: "mylib.retry"
  treat-as: config
  where:
  - param: condition
    flatten-on: "|"
    where:
    - match: "on_status"
      where:
      - param: code
        assign-to: spec.resiliency.retryOnStatus
    - match: "on_exception"
      where:
      - param: exc_type
        assign-to: spec.resiliency.retryOnException
```

This handles:

```python
@retry(condition=on_status(429) | on_exception(TimeoutError))
def api_call(p: dict) -> dict: ...
```

### Context manager rules

Context manager rules work the same way — the parser auto-detects that a `with`
statement triggers the rule:

```yaml
- match: "mylib.batch_config"
  treat-as: config
  where:
  - param: size
    assign-to: spec.scaling.batchSize
```

```python
async with mylib.batch_config(size=50):
    p = process_batch(p)
    p = store_batch(p)
```

Both `process_batch` and `store_batch` get `spec.scaling.batchSize: 50` in
their manifests.

---

## Inline comment overrides

For per-statement control without writing a rule, use `# asya: <action>`
comments:

```python
@flow
def pipeline(p: dict) -> dict:
    p = normalize(p)       # asya: inline   — run inside router, no queue hop
    p = validate(p)        # asya: actor    — separate actor (explicit)
    p = enrich(p)                           — default classification
    return p
```

Supported actions: `actor`, `inline`, `unfold`, `flow`, `config`.

Inline comments have the **highest priority** — they override all rules and
defaults.

The syntax follows standard Python tool conventions (`# type: ignore`,
`# noqa: E501`).

---

## Definition-site and call-site decorators

Beyond config rules, the compiler recognizes classification decorators on
function definitions:

```python
@actor
def validate(p: dict) -> dict: ...    # always a separate actor

@inline
def inject_trace(p: dict) -> dict: ... # always inlined into router
```

And call-site wrappers for functions defined elsewhere:

```python
p = actor(external_lib.validate)(p)    # force actor boundary
p = inline(external_lib.normalize)(p)  # force inline
```

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

The outer 60s timeout applies to all three actors. The inner 10s timeout
applies only to `parse` and `validate`. The `store` actor has no timeout.

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

The `examples/flows/` directory contains working examples:

| File | Demonstrates |
|------|--------------|
| `decorator_retry.py` | `@retry` with config extraction |
| `with_asyncio_timeout.py` | `asyncio.timeout` context manager |
| `with_nested_timeout_scopes.py` | Nested timeout scopes |
| `decorator_definitions.py` | `@actor` and `@inline` definition-site decorators |
| `decorator_callsite.py` | `actor(fn)(p)` call-site wrappers |
| `inline_comment_overrides.py` | `# asya: actor` / `# asya: inline` overrides |

Compile any example:

```bash
asya flow compile examples/flows/decorator_retry.py --output-dir compiled/ --verbose
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
