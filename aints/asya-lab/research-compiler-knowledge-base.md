# Research: Compiler Rules — Extensible Static Analysis for Flow DSL

**Date**: 2026-03-08
**Related aints**: [n67c] (decorator strategy), [1mhs] (dive into functions), [1fmi] (tenacity detection), [zjt4] (cumulative retry window)

---

## Problem

The Asya flow compiler needs to make decisions about every symbol it encounters:
decorators, function calls, context managers, module imports. Currently it has no
configurable knowledge base — every `p = func(p)` is assumed to be an actor
boundary, decorators are ignored, and there is no way to teach the compiler about
third-party frameworks (tenacity, stamina, asyncio.timeout).

Users should not need to learn custom Asya retry/timeout decorators, and Asya
maintainers should not need to ship per-framework support code. Instead, the
compiler should be extensible via declarative configuration.

## Design

### `treat-as` Values

Every symbol the compiler encounters is classified into exactly one of five actions:

| Value | Meaning | Body inspected? | Creates boundary? |
|-------|---------|-----------------|-------------------|
| `decompose` | Expand function body into current flow's routers | Yes | No |
| `inline` | Run code inside router verbatim | No | No |
| `actor` | Message boundary, separate deployment | No | Yes |
| `flow` | Sub-flow, compile recursively | Yes | Yes |
| `config` | Infrastructure metadata — strip and extract | No | No |

### Rules

Rules are declared in `asya.yaml` under `compiler.rules`. Each rule matches a
symbol pattern and assigns a `treat-as` classification.

```yaml
compiler:
  rules:
    - module: "."
      treat-as: decompose

    - module: "*"
      treat-as: inline

    - module: "actor"
      treat-as: actor

    - module: "flow"
      treat-as: flow

    - module: "tenacity.retry"
      treat-as: config
      extract:
        stop_after_attempt:
          max_attempt_number: ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS
        stop_after_delay:
          max_delay: ASYA_RESILIENCY_RETRY_MAX_WINDOW
        wait_exponential:
          min: ASYA_RESILIENCY_RETRY_INITIAL_INTERVAL
          max: ASYA_RESILIENCY_RETRY_MAX_INTERVAL
          multiplier: ASYA_RESILIENCY_RETRY_BACKOFF_COEFFICIENT
        wait_fixed:
          wait: ASYA_RESILIENCY_RETRY_INITIAL_INTERVAL
        wait_random:
          max: ASYA_RESILIENCY_RETRY_JITTER
        retry_if_exception_type:
          exception_types: ASYA_RESILIENCY_NON_RETRYABLE_ERRORS

    - module: "stamina.retry"
      treat-as: config
      extract:
        stamina.retry:
          attempts: ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS
          timeout: ASYA_RESILIENCY_ACTOR_TIMEOUT
          wait_initial: ASYA_RESILIENCY_RETRY_INITIAL_INTERVAL
          wait_max: ASYA_RESILIENCY_RETRY_MAX_INTERVAL
          wait_exp_base: ASYA_RESILIENCY_RETRY_BACKOFF_COEFFICIENT

    - module: "asyncio.timeout"
      treat-as: config
      extract:
        asyncio.timeout:
          delay: ASYA_RESILIENCY_ACTOR_TIMEOUT
```

### Pattern Matching: Most Specific Wins

Rule order does not matter. The most specific matching pattern wins:

| Specificity | Pattern | Example | Matches |
|-------------|---------|---------|---------|
| 1 (highest) | Exact name | `tenacity.retry` | Only `tenacity.retry` |
| 2 | Prefix wildcard | `tenacity.*` | Anything under `tenacity` |
| 3 | Current project | `.` | Same project tree as flow file |
| 4 (lowest) | Global wildcard | `*` | Everything |

Among patterns with the same specificity, longer prefix wins
(`numpy.linalg.*` beats `numpy.*`).

### Per-Call-Site Overrides (Inline Comments)

Any rule can be overridden at the call site using inline comments:

```python
p = handler(p)              # asya: treat-as-actor
p = handler(p)              # asya: treat-as-inline
p["id"] = str(uuid4())      # asya: treat-as-inline
p = sub_pipeline(p)         # asya: treat-as-flow
p = handler(p)              # asya: treat-as-decompose
```

Inline comments have the highest priority, overriding all rules.

### Multiple Rules on the Same Function

A function with multiple decorators matches rules independently per decorator:

```python
@actor
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=60))
async def llm_call(state: dict) -> dict:
    ...
```

- `actor` matches rule `treat-as: actor` — determines call resolution
- `tenacity.retry` matches rule `treat-as: config` — strips decorator, extracts env vars

These compose: the function is an actor boundary AND has its retry decorator
stripped with config extracted.

### Call-Site Decorator Application

The `actor` and `flow` markers can also be applied at the call site:

```python
p = actor(handler)(p)       # treat handler as actor (same as @actor on definition)
p = inline(uuid4)(p)        # treat uuid4 as inline code
```

The compiler recognizes `actor` and `inline` from the same rules — no separate
"wrapper" concept. Python's decorator and call-site application are equivalent.

### Config Extraction via Runtime Introspection

When `treat-as: config` is used, the `extract` section maps parameter names to
Asya environment variables. The extraction uses **Python runtime introspection**
at compile time:

1. Compiler encounters `@retry(wait=wait_exponential(1, 4, 10))` in the AST
2. Compiler imports `tenacity.wait_exponential` (package must be installed)
3. Calls `inspect.signature(wait_exponential.__init__)` to get param names:
   `(multiplier, max, exp_base, min)`
4. Binds positional args `(1, 4, 10)` to params: `{multiplier: 1, max: 4, exp_base: 10}`
5. Looks up extraction rules: `min -> ASYA_RESILIENCY_RETRY_INITIAL_INTERVAL`, etc.

This handles all calling conventions automatically:
- `wait_exponential(1, 4, 10)` — positional
- `wait_exponential(multiplier=1, max=10)` — keyword
- `wait_exponential(1, max=10)` — mixed

The extract config is a flat map of `param_name: ENV_VAR`. No AST path
expressions needed.

**BinOp handling**: Combinations like `wait_fixed(3) + wait_random(0, 2)` or
`stop_after_attempt(5) | stop_after_delay(30)` are flattened — the compiler
walks the binary operation tree, extracts each `Call` node, and matches it
against extraction rules independently.

**Bare decorators**: `@retry` with no arguments — no inner classes to match,
compiler strips the decorator and uses Asya defaults.

### Context Managers

Context managers (e.g., `async with asyncio.timeout(30):`) are matched by the
same rules as decorators. The compiler recognizes the symbol name and applies
`treat-as` accordingly:

```python
async def my_flow(p: dict) -> dict:
    async with asyncio.timeout(30):   # matched by "asyncio.timeout" rule
        p = slow_handler(p)           # actors inside the scope
    return p
```

When `treat-as: config`, the context manager is stripped and its arguments are
extracted using the same `inspect.signature` mechanism.

### Asya Resiliency Env Vars (Extraction Targets)

These are the currently implemented env vars that extraction rules can target:

| Env Var | Type | Default | Concept |
|---------|------|---------|---------|
| `ASYA_RESILIENCY_RETRY_POLICY` | "constant"\|"exponential" | "exponential" | Backoff strategy |
| `ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS` | int | 3 | Max attempts |
| `ASYA_RESILIENCY_RETRY_INITIAL_INTERVAL` | duration | "1s" | Backoff initial delay |
| `ASYA_RESILIENCY_RETRY_MAX_INTERVAL` | duration | "300s" | Backoff max delay |
| `ASYA_RESILIENCY_RETRY_BACKOFF_COEFFICIENT` | float | 2.0 | Exponential base |
| `ASYA_RESILIENCY_RETRY_JITTER` | bool | true | Jitter enabled |
| `ASYA_RESILIENCY_NON_RETRYABLE_ERRORS` | csv | (none) | Exception blacklist |
| `ASYA_RESILIENCY_ACTOR_TIMEOUT` | duration | "5m" | Per-call timeout |

Not yet implemented (see [zjt4]):

| Env Var | Type | Default | Concept |
|---------|------|---------|---------|
| `ASYA_RESILIENCY_RETRY_MAX_WINDOW` | duration | (none) | Cumulative retry window |

## Defaults

| Situation | Default behavior | Override mechanism |
|-----------|-----------------|-------------------|
| Same-package function, no rule | `decompose` (via `"."` rule) | Inline comment or specific rule |
| External function, no rule | `inline` (via `"*"` rule) | Specific rule |
| Decorator, no rule | Keep at runtime | `treat-as: config` rule to strip |

## Research: Python Retry/Timeout Decorator Landscape

The extraction syntax was validated against these libraries:

### Retry libraries

| Library | Decorator | Arg style |
|---------|-----------|-----------|
| tenacity | `@retry(stop=stop_after_attempt(3))` | Nested class instantiation (classes, not functions) |
| stamina | `@retry(attempts=10, timeout=45.0)` | Flat kwargs |
| backoff | `@on_exception(backoff.expo, Exception, max_tries=3)` | Positional + kwargs |
| opnieuw | `@retry(max_calls_total=3)` | Flat kwargs |

### Timeout libraries

| Library | Decorator/CM | Arg style |
|---------|-------------|-----------|
| asyncio | `async with asyncio.timeout(30)` | Context manager, single positional |
| timeout_decorator | `@timeout(seconds=30)` | Single kwarg |
| stopit | `@threading_timeoutable()` | Kwargs |

Runtime `inspect.signature` handles all arg styles (positional, keyword, mixed)
uniformly, eliminating the need for AST path expressions in the config.

### Tenacity class signatures (verified)

```
wait_exponential(multiplier=1, max=4.6e+18, exp_base=2, min=0)
wait_fixed(wait)
wait_random(min=0, max=1)
stop_after_attempt(max_attempt_number)
stop_after_delay(max_delay)
retry_if_exception_type(exception_types=<class 'Exception'>)
```

## Open Questions

1. **`retry_if_exception_type` inversion**: Tenacity uses a whitelist ("retry ON
   these"), Asya uses a blacklist (`nonRetryableErrors`). Should the compiler
   handle the inversion automatically, or skip exception extraction and let users
   configure manually?

2. **Compile-time dependency requirement**: `treat-as: config` with `extract`
   requires the decorator package to be installed at compile time for
   `inspect.signature`. This is natural (the flow file imports it), but should be
   documented as a requirement.

3. **Context manager scope semantics**: When `asyncio.timeout(30)` wraps multiple
   actor calls, does the extracted timeout apply to each actor individually or to
   the scope as a whole? Current design: per-actor (each actor in the scope gets
   the extracted config). Flow-level timeout is handled by the gateway's
   `deadline_at` mechanism.
