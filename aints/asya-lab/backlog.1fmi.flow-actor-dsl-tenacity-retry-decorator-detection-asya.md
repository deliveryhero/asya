---
title: "Compiler knowledge base: treat-as rules engine with default rule set"
priority: 3 # low
tags:
  - type:feature
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

1. **Rules engine** — load `compile.rules` from `.asya/config.yaml`, match
   symbols against patterns, classify each as one of five `treat-as` actions
2. **Default rule set** — ship sensible defaults that work without config:
   - `module: "."` → `treat-as: unfold` (same-package functions)
   - `module: "*"` → `treat-as: inline` (external code)
   - `module: "actor"` → `treat-as: actor`
   - `module: "flow"` → `treat-as: flow`
3. **Built-in config extraction rules** for common frameworks:
   - `tenacity.retry` → `treat-as: config` + `extract:` (retry env vars)
   - `stamina.retry` → `treat-as: config` + `extract:` (retry env vars)
   - `asyncio.timeout` → `treat-as: config` + `extract:` (timeout env var)
4. **Pattern matching** — most-specific-wins resolution (exact > prefix
   wildcard > `.` > `*`)
5. **Config extraction** — `inspect.signature` at compile time for binding
   decorator args to `ASYA_RESILIENCY_*` env vars
6. **Testing** — validate on `examples/flows/` with mixed decorators,
   context managers, and inline overrides

## Blocked by

- `.asya/config.yaml` schema design (WIP — see
  `.aint/aints/asya-lab/research-compiler-resolution.md`). The `compile.rules`
  section needs to be part of the config schema before rules can be loaded.

## Dependencies

- [pyn3] Inline comment overrides (`# asya: <action>`) — merged/in progress
- [srn2] Decorator detection and rule-based resolution
- [2t1q] Context manager support (`with`/`async with`)
- [xx8t] Call-site decorator application (`actor(handler)(p)`)
- [zjt4] Cumulative retry time window (`ASYA_RESILIENCY_RETRY_MAX_WINDOW`)

## Design references

- **Rules design**: `.aint/aints/asya-lab/research-compiler-knowledge-base.md`
- **Config schema**: `.aint/aints/asya-lab/research-compiler-resolution.md`
- **Resiliency env vars**: `.aint/aints/.closed/error-handling/rfc.md`
- **Decorator strategy resolution**: [n67c]

## Asya resiliency env vars (extraction targets)

| Env Var | Type | Default |
|---------|------|---------|
| `ASYA_RESILIENCY_RETRY_POLICY` | "constant"\|"exponential" | "exponential" |
| `ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS` | int | 3 |
| `ASYA_RESILIENCY_RETRY_INITIAL_INTERVAL` | duration | "1s" |
| `ASYA_RESILIENCY_RETRY_MAX_INTERVAL` | duration | "300s" |
| `ASYA_RESILIENCY_RETRY_BACKOFF_COEFFICIENT` | float | 2.0 |
| `ASYA_RESILIENCY_RETRY_JITTER` | bool | true |
| `ASYA_RESILIENCY_NON_RETRYABLE_ERRORS` | csv | (none) |
| `ASYA_RESILIENCY_ACTOR_TIMEOUT` | duration | "5m" |
| `ASYA_RESILIENCY_RETRY_MAX_WINDOW` | duration | (none) — see [zjt4] |

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
