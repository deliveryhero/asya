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
| `unfold` | Expand function body into current flow's routers | Yes | No |
| `inline` | Run code inside router verbatim | No | No |
| `actor` | Message boundary, separate deployment | No | Yes |
| `flow` | Sub-flow, compile recursively | Yes | Yes |
| `config` | Infrastructure metadata — strip and extract | No | No |

### Rules

Rules are declared in `config.compiler.yaml`. Each rule has a `match:` pattern
and either a `treat-as:` classification or a `where:` extraction tree (or both).

Two rule types:
- **Classification rules**: `match:` + `treat-as:` — classify a symbol
- **Extraction rules**: `match:` + `where:` — navigate AST and extract values
  to XR spec paths (implicitly `treat-as: config`)

```yaml
# config.compiler.yaml
rules:
  # --- Classification rules ---
  - match: "."
    treat-as: unfold

  - match: "*"
    treat-as: inline

  - match: "actor"
    treat-as: actor

  - match: "flow"
    treat-as: flow

  # --- Extraction rules (decorator → XR spec paths) ---
  - match: "tenacity.retry"
    where:
      - param: stop
        where:
          - param: max_attempt_number
            assign-to: spec.resiliency.retry.maxAttempts
            example: "@retry(stop=stop_after_attempt(N))"
          - param: max_delay
            assign-to: spec.resiliency.retry.maxWindow
            example: "@retry(stop=stop_after_delay(N))"
      - param: wait
        where:
          - param: min
            assign-to: spec.resiliency.retry.initialInterval
            example: "@retry(wait=wait_exponential(min=N))"
          - param: max
            assign-to: spec.resiliency.retry.maxInterval
            example: "@retry(wait=wait_exponential(max=N))"
          - param: multiplier
            assign-to: spec.resiliency.retry.backoffCoefficient
            example: "@retry(wait=wait_exponential(multiplier=N))"
          - param: wait
            assign-to: spec.resiliency.retry.initialInterval
            example: "@retry(wait=wait_fixed(N))"
          - param: max
            assign-to: spec.resiliency.retry.jitter
            example: "@retry(wait=wait_random(max=N))"
      - param: retry
        where:
          - match: retry_if_exception_type
            where:
              - param: exception_types
                assign-to: spec.resiliency.retryableErrors
                example: "@retry(retry=retry_if_exception_type(E))"
          - match: retry_if_not_exception_type
            where:
              - param: exception_types
                assign-to: spec.resiliency.nonRetryableErrors
                example: "@retry(retry=retry_if_not_exception_type(E))"

  - match: "stamina.retry"
    where:
      - param: attempts
        assign-to: spec.resiliency.retry.maxAttempts
        example: "@stamina.retry(attempts=N)"
      - param: timeout
        assign-to: spec.resiliency.timeout
        example: "@stamina.retry(timeout=N)"
      - param: wait_initial
        assign-to: spec.resiliency.retry.initialInterval
        example: "@stamina.retry(wait_initial=N)"
      - param: wait_max
        assign-to: spec.resiliency.retry.maxInterval
        example: "@stamina.retry(wait_max=N)"
      - param: wait_exp_base
        assign-to: spec.resiliency.retry.backoffCoefficient
        example: "@stamina.retry(wait_exp_base=N)"

  - match: "asyncio.timeout"
    where:
      - param: delay
        assign-to: spec.resiliency.timeout
        example: "asyncio.timeout(N)"

  # --- Environment variable detection ---
  - match: os
    where:
      - access: [getenv, environ.get, environ.__getitem__]
        assign-to: env
        example: "os.environ['KEY'] / os.getenv('KEY', 'default')"
        where:
          - param: 0
            assign-to: env.name
            example: "os.getenv('NAME', ...)"
          - param: 1
            assign-to: env.default
            example: "os.getenv('NAME', 'default_value')"
```

### Rule Tree Structure (`where:`)

Each node in a `where:` tree has:

| Field | Purpose |
|-------|---------|
| `param:` | Navigate to this parameter (by name or position) |
| `access:` | Match access pattern (method call, dunder) |
| `where:` | Continue navigating deeper (recursive) |
| `assign-to:` | Terminal — extract value and place at XR spec path |
| `example:` | Self-documenting — Python syntax this node matches |

Rules navigate the AST tree recursively. The compiler uses `inspect.signature`
at each level to resolve parameter names from positional/keyword args.

**BinOp handling**: When a param holds a binary operation like
`stop_after_attempt(5) | stop_after_delay(30)`, the compiler flattens the
BinOp tree and matches each `Call` node independently against the `where:`
children. Param names serve as discriminators — `stop_after_attempt` has
`max_attempt_number`, `stop_after_delay` has `max_delay`.

### Environment Variable Detection

The `os` rule detects env var access in handler code:

| Python pattern | How detected |
|---------------|-------------|
| `os.environ["KEY"]` | `access: environ.__getitem__`, param 0 = key |
| `os.environ.get("KEY")` | `access: environ.get`, param 0 = key |
| `os.environ.get("KEY", "default")` | param 0 = key, param 1 = default |
| `os.getenv("KEY")` | `access: getenv`, param 0 = key |
| `os.getenv("KEY", "default")` | param 0 = key, param 1 = default |

`assign-to: env` is a semantic shorthand — the compiler constructs a K8s env
entry per detected variable. `env.name` receives the variable name, `env.default`
receives the default value (if present).

For K8s sourcing (secret refs), see the `secrets:` section in `config.yaml`.

### Secrets Mapping (`secrets:` in config.yaml)

Env var detection produces variable names. The `secrets:` section in
`config.yaml` maps those names to K8s secret references:

```yaml
# config.yaml
secrets:
  OPENAI_API_KEY:
    secret: llm-secrets
    key: openai-api-key
  DB_PASSWORD:
    secret: database-creds
    key: password
  "*":
    secret: "${var.default_secret}"
```

When the compiler detects `os.environ["OPENAI_API_KEY"]` in handler code:
1. Rule matches → extracts var name "OPENAI_API_KEY" and (no default)
2. Looks up "OPENAI_API_KEY" in `secrets:` → found
3. Generates: `{name: "OPENAI_API_KEY", valueFrom: {secretKeyRef: {name: "llm-secrets", key: "openai-api-key"}}}`

When the compiler detects `os.getenv("MODEL_NAME", "gpt-4")`:
1. Rule matches → extracts var name "MODEL_NAME" and default "gpt-4"
2. Looks up "MODEL_NAME" in `secrets:` → not found, no `"*"` fallback
3. Generates: `{name: "MODEL_NAME", value: "gpt-4"}`

Unmatched env vars with no default and no `"*"` rule → warning (detected but
no source configured).

Managed via CLI: `asya secret create/remove/list` (see CLI section below).

### `asya compiler-rule` CLI

```bash
# Add extraction rules — Python pattern with capture markers
asya compiler-rule add \
  "tenacity.retry(stop=stop_after_attempt(X))" \
  --assign-to spec.resiliency.retry.maxAttempts

asya compiler-rule add \
  "tenacity.retry(wait=wait_exponential(min=X))" \
  --assign-to spec.resiliency.retry.initialInterval

# Env var detection — multiple captures with --assign-from
asya compiler-rule add "os.getenv(NAME, DEFAULT)" \
  --assign-from NAME --assign-to env.name \
  --assign-from DEFAULT --assign-to env.default

asya compiler-rule add "os.environ[NAME]" \
  --assign-from NAME --assign-to env.name

# Classification rule (no capture, no --assign-to)
asya compiler-rule add "my_lib.helper" --treat-as inline

# List all rules (built-in + project)
asya compiler-rule list

# Remove a rule (or a single extraction path from it)
asya compiler-rule remove "my_lib.helper"

# Explain: show what the compiler would do with a given symbol
asya compiler-rule explain "tenacity.retry"
# → match: tenacity.retry
# → where: tree with 7 extraction paths
# → extracts:
# →   stop.max_attempt_number → spec.resiliency.retry.maxAttempts
# →     example: tenacity.retry(stop=stop_after_attempt(X))
# →   wait.min → spec.resiliency.retry.initialInterval
# →     example: tenacity.retry(wait=wait_exponential(min=X))
# →   ...
```

**`--assign-from` / `--assign-to` flags**:

| Flag | Purpose | Default |
|------|---------|---------|
| `--assign-from` | Name of the capture marker in the pattern | `X` |
| `--assign-to` | XR spec path where the captured value goes | (required for extraction) |

Multiple `--assign-from`/`--assign-to` pairs extract multiple values from
one pattern. Each pair creates a terminal `where:` node with `assign-to:`
and `example:`.

**How `add` works**:
1. Parses the Python-like expression (`ast.parse`-compatible)
2. Capture markers (default `X`, or named via `--assign-from`) mark values
   to extract — each becomes a terminal `assign-to:` node
3. Builds a nested `where:` tree from the expression structure
4. The original string becomes the `example:` field automatically
5. If a rule for the same match already exists, appends to its `where:` tree
6. Writes `config.compiler.yaml`, shows git diff
7. **Refuses to write if file has uncommitted changes** (unless `--force`)

### `asya secret` CLI

```bash
# Register a secret mapping
asya secret create OPENAI_API_KEY --secret llm-secrets --key openai-api-key

# Remove a mapping
asya secret remove OPENAI_API_KEY

# List all mappings
asya secret list
```

`asya secret` manages the `secrets:` section in `config.yaml`. The actual
K8s Secret is managed separately (kubectl, Vault, ExternalSecrets, etc.).
Same safety rule: refuses to write if `config.yaml` has uncommitted changes.

### File Safety: Git-Clean Guard

All asya commands that generate or modify files refuse to overwrite unless
the target file is git-committed (clean). This prevents accidental loss of
manual edits.

| Command | Modified file | Guard |
|---------|--------------|-------|
| `asya flow compile` | routers.py, manifests | Git-clean or `--force` |
| `asya compiler-rule add/remove` | config.compiler.yaml | Git-clean or `--force` |
| `asya secret create/remove` | config.yaml | Git-clean or `--force` |
| `asya init` | `.asya/*` | Directory must not exist or `--force` |

All commands show the git diff of their changes after writing.

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
p = handler(p)              # asya: actor
p = handler(p)              # asya: inline
p["id"] = str(uuid4())      # asya: inline
p = sub_pipeline(p)         # asya: flow
p = handler(p)              # asya: unfold
```

Follows standard Python tool comment conventions (`# type: ignore`, `# noqa: E501`,
`# pragma: no cover`): short prefix + action word. No infrastructure parameters
(actor names, config values) — flow definitions stay pure business logic.

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
- `tenacity.retry` matches rule with `where:` tree — strips decorator, extracts
  values to XR spec paths

These compose: the function is an actor boundary AND has its retry decorator
stripped with config extracted.

### Call-Site Decorator Application

The `treat-as` markers can also be applied at the call site:

```python
p = actor(handler)(p)       # treat handler as actor (same as @actor on definition)
p = inline(uuid4)(p)        # treat uuid4 as inline code
p = unfold(helper)(p)       # expand helper's body into current flow
```

The compiler recognizes `actor`, `inline`, and `unfold` from the same rules — no
separate "wrapper" concept. Python's decorator and call-site application are
equivalent.

### Value Extraction via Runtime Introspection

When a rule has a `where:` tree, the compiler uses **Python runtime
introspection** at compile time to resolve parameter names:

1. Compiler encounters `@retry(wait=wait_exponential(1, 4, 10))` in the AST
2. Rule matches `tenacity.retry` → navigates `where: param: wait`
3. Compiler imports `tenacity.wait_exponential` (package must be installed)
4. Calls `inspect.signature(wait_exponential.__init__)` to get param names:
   `(multiplier, max, exp_base, min)`
5. Binds positional args `(1, 4, 10)` to params: `{multiplier: 1, max: 4, exp_base: 10}`
6. Matches `where:` children: `param: min` → found, value = 0 →
   `assign-to: spec.resiliency.retry.initialInterval`

This handles all calling conventions automatically:
- `wait_exponential(1, 4, 10)` — positional
- `wait_exponential(multiplier=1, max=10)` — keyword
- `wait_exponential(1, max=10)` — mixed

**Bare decorators**: `@retry` with no arguments — no `where:` children match,
compiler strips the decorator and uses Asya defaults.

**Hard requirement: well-configured Python environment.** `asya compile` must
run in the project's virtualenv with all decorator/library packages installed.
The compiler imports library packages referenced in extraction rules (tenacity,
stamina, etc.) to call `inspect.signature` — same requirement as mypy or
pyright. User handler code is never imported (only parsed via `ast.parse`),
so heavy-init side effects (model loading, GPU) are not a concern. Only
decorator/library packages are imported, and these are lightweight by nature.

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

### XR Spec Paths (Extraction Targets)

Rules extract values from Python AST and place them at these AsyncActor XR
spec paths:

| XR Spec Path | Type | Default | Concept |
|-------------|------|---------|---------|
| `spec.resiliency.retry.maxAttempts` | int | 3 | Max attempts |
| `spec.resiliency.retry.initialInterval` | duration | "1s" | Backoff initial delay |
| `spec.resiliency.retry.maxInterval` | duration | "300s" | Backoff max delay |
| `spec.resiliency.retry.backoffCoefficient` | float | 2.0 | Exponential base |
| `spec.resiliency.retry.jitter` | bool | true | Jitter enabled |
| `spec.resiliency.retry.maxWindow` | duration | (none) | Cumulative retry window |
| `spec.resiliency.retryableErrors` | csv | (none) | Exception whitelist (only retry these) |
| `spec.resiliency.nonRetryableErrors` | csv | (none) | Exception blacklist (don't retry these) |
| `spec.resiliency.timeout` | duration | "5m" | Per-call timeout |
| `env` | list | [] | K8s env entries (semantic shorthand) |

The `env` target is a semantic shorthand — the compiler expands it to a K8s
env entry list at `spec.workload.template.spec.containers[].env`. See
"Environment Variable Detection" above.

## Defaults and Explicit Markers

The default for same-package functions is `unfold` — the compiler expands their
body into the current flow's routers. This is safe because:

- **Actors are always explicit**: `@actor` decorator or `# asya: actor` comment.
  No function becomes an actor boundary by default.
- **Flows are always explicit**: `@flow` decorator or `# asya: flow` comment.
- **Unfold of simple utilities is harmless**: a function that just does dict
  mutations unfolds into inline mutations — same result as `inline`.
- **Unfold of complex utilities fails loudly**: if the body contains unsupported
  constructs (loops, complex logic), the compiler errors with a clear message
  → user adds `# asya: inline`.

| Marker | Syntax options | Effect |
|--------|---------------|--------|
| `actor` | `@actor`, `# asya: actor`, `actor(func)(p)` | Message boundary, separate deployment |
| `flow` | `@flow`, `# asya: flow` | Sub-flow, compile recursively |
| `inline` | `@inline`, `# asya: inline`, `inline(func)(p)` | Run verbatim in router |
| `unfold` | `@unfold`, `# asya: unfold`, `unfold(func)(p)` | Expand body into current flow (default for same-package) |

| Situation | Default behavior | Override mechanism |
|-----------|-----------------|-------------------|
| Same-package function, no rule | `unfold` (via `"."` rule) | Any marker above |
| External function, no rule | `inline` (via `"*"` rule) | Any marker above |
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

1. ~~**`retry_if_exception_type` inversion**~~ **Resolved**: Add `retryableErrors`
   whitelist to the sidecar alongside `nonRetryableErrors`. No inversion needed —
   the compiler maps directly:

   | Tenacity | Asya spec path | Semantics |
   |----------|---------------|-----------|
   | `retry_if_exception_type(E)` | `spec.resiliency.retryableErrors` | Whitelist — only retry these |
   | `retry_if_not_exception_type(E)` | `spec.resiliency.nonRetryableErrors` | Blacklist — don't retry these |

   Both sides already speak FQNs: the runtime sends `module.qualname` via
   `_fqn()` (builtins omit module prefix), the sidecar matches strings against
   errorType + MRO ancestors. The compiler resolves FQNs at compile time via
   `inspect` + the same `_fqn` logic.

   Sidecar change: `isNonRetryableError` becomes `shouldRetry` checking both
   lists (mutually exclusive). See aint [w76v].

2. ~~**Compile-time dependency requirement**~~ **Resolved**: Already documented in
   "Value Extraction via Runtime Introspection" section above and RFC §14.
   The compiler imports packages and calls `inspect.signature` — same as
   mypy/pyright requiring deps installed. Natural since the flow file already
   imports the package.

3. ~~**Context manager scope semantics**~~: **Resolved**. Per-scope, not
   per-actor. `asyncio.timeout(30)` wrapping 3 actors = 30s total for the
   pipeline segment, not 30s per actor. All compiler rules apply per scope:
   context manager body, decorated function, or single call. See aint [ia37].
