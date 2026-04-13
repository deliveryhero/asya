---
title: "Compiler knowledge base: treat-as rules engine with default rule set"
status: merged
priority: 2
assignee: Artem Yushkovskiy
parent: drsjr
tags:
  - type:feature
  - worktree:.worktrees/.worktrees/asya-lab/1fmi.flow-actor-dsl-tenacity-retry-decorator-detection-asya
  - branch:asya-lab/1fmi.flow-actor-dsl-tenacity-retry-decorator-detection-asya
  - pr:307
  - pr:329
---

## Problem

The flow compiler has no configurable knowledge base. Every `p = func(p)` is
assumed to be an actor boundary, decorators are ignored, and there is no way to
teach the compiler about third-party frameworks (tenacity, stamina,
asyncio.timeout). The `treat-as` vocabulary (`actor`, `flow`, `unfold`,
`inline`, `config`) is designed but not implemented as a rules engine.

## Scope

Implement the compiler rules system described in
`.aint/aints/asya-lab/research-compiler-knowledge-base.md`:

1. **Rules engine** — load `rules` from `.asya/config.compiler.yaml`, match
   symbols against patterns, classify each as one of five `treat-as` actions
2. **Default rule set** — ship sensible defaults that work without config:
   - `module: "."` → `treat-as: unfold` (same-package functions)
   - `module: "*"` → `treat-as: inline` (external code)
   - `module: "actor"` → `treat-as: actor`
   - `module: "flow"` → `treat-as: flow`
3. **Built-in extraction rules** for common frameworks:
   - `tenacity.retry` → `where:` tree → `assign-to: spec.resiliency.*`
   - `stamina.retry` → `where:` tree → `assign-to: spec.resiliency.*`
   - `asyncio.timeout` → `where:` tree → `assign-to: spec.resiliency.timeout`
   - `os` → `where: access:` → `assign-to: env` (env var detection)
4. **Pattern matching** — most-specific-wins resolution (exact > prefix
   wildcard > `.` > `*`)
5. **Value extraction** — `inspect.signature` at compile time for binding
   decorator args; `where:`/`assign-to:` tree syntax places values at XR
   spec paths
6. **Secrets mapping** — `secrets:` section in config.yaml for env var →
   K8s secretKeyRef mapping
7. **CLI** — `asya compiler-rule add/remove/list/explain` and
   `asya secret create/remove/list`
6. **Testing** — validate on `examples/flows/` with mixed decorators,
   context managers, and inline overrides

## Blocked by

- ~~`.asya/config.yaml` schema design~~ **Resolved** — config refactor merged
  (`423bf76a`). Rules now live in `.asya/config.compiler.yaml` under the
  `rules:` key (filename-to-key convention). See
  `.aint/aints/asya-lab/refactor-config-with-templates.md` for the design.

## Dependencies

- [pyn3] Inline comment overrides (`# asya: <action>`) — merged/in progress
- [srn2] Decorator detection and rule-based resolution
- [2t1q] Context manager support (`with`/`async with`)
- [xx8t] Call-site decorator application (`actor(handler)(p)`)
- [zjt4] Cumulative retry time window (`spec.resiliency.retry.maxWindow`)

## Design references

- **Rules design**: `.aint/aints/asya-lab/research-compiler-knowledge-base.md`
- **Config refactor**: `.aint/aints/asya-lab/refactor-config-with-templates.md`
- **Config schema**: `.aint/aints/asya-lab/research-compiler-resolution.md`
- **Resiliency env vars**: `.aint/aints/.closed/error-handling/rfc.md`
- **Decorator strategy resolution**: [n67c]

## XR spec paths (extraction targets)

| XR Spec Path | Type | Default |
|-------------|------|---------|
| `spec.resiliency.retry.maxAttempts` | int | 3 |
| `spec.resiliency.retry.initialInterval` | duration | "1s" |
| `spec.resiliency.retry.maxInterval` | duration | "300s" |
| `spec.resiliency.retry.backoffCoefficient` | float | 2.0 |
| `spec.resiliency.retry.jitter` | bool | true |
| `spec.resiliency.retry.maxWindow` | duration | (none) — see [zjt4] |
| `spec.resiliency.nonRetryableErrors` | csv | (none) |
| `spec.resiliency.timeout` | duration | "5m" |
| `env` | list | [] — K8s env entries (semantic shorthand) |

## Research: Python retry/timeout decorator landscape

### Retry libraries — argument structures

| Library | Decorator | Max attempts | Timeout/Window | Backoff | Exceptions |
|---------|-----------|-------------|----------------|---------|------------|
| **tenacity** | `@retry(...)` | `stop=stop_after_attempt(3)` | `stop=stop_after_delay(30)` | `wait=wait_exponential(min=1, max=60)` | `retry=retry_if_exception_type(...)` |
| **stamina** | `@retry(...)` | `attempts=10` | `timeout=45.0` | `wait_initial=0.1, wait_max=5.0, wait_exp_base=2` | `on=Exception` |
| **backoff** | `@on_exception(...)` | `max_tries=3` | `max_time=60` | `wait_gen=backoff.expo` (positional!) | `exception=Exception` (positional!) |
| **opnieuw** | `@retry(...)` | `max_calls_total=3` | `retry_window_after_first_call_in_seconds=60` | (implicit full jitter) | `retry_on_exceptions=(Exc,)` |

### Timeout libraries

| Library | Decorator | Timeout value |
|---------|-----------|--------------|
| **timeout_decorator** | `@timeout(30)` | positional `seconds=30` |
| **stopit** | `@threading_timeoutable()` | `default=None, timeout_param='timeout'` |
| **asyncio** | `asyncio.timeout(30)` | context manager, not a decorator |

### Config extraction approach

Runtime `inspect.signature` at compile time handles all arg styles (positional,
keyword, mixed) uniformly. Tenacity uses classes (not functions) for strategy
objects — `inspect.signature(cls.__init__)` resolves parameter names. BinOp
combinations (`wait_fixed(3) + wait_random(0, 2)`) are flattened by walking the
AST binary operation tree.

See research-compiler-knowledge-base.md for full extraction design and verified
tenacity class signatures.
