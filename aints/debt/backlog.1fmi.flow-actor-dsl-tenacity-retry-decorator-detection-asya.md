---
title: "Flow/Actor DSL: tenacity.retry decorator detection and resiliency config generation"
priority: 3 # low
tags:
  - type:feature
---

see `.aint/aints/.closed/error-handling/rfc.md` for resiliency configuration.

Extend Flow DSL compiler (and potentially Actor DSL) to detect retry/timeout decorators on actor handler functions. When detected: (1) strip the decorator for Asya-managed retry (handler runs pure), (2) extract retry config from decorator arguments, (3) generate corresponding `ASYA_RESILIENCY_*` env vars for the AsyncActor CRD. This provides familiar Python syntax for retry configuration while keeping the actual retry at infrastructure level via the sidecar.

Should work on both actors (decorator) and regular functions to dive in (see `.aint/aints/support-more-compiler-constructs/.closed/merged.1mhs.dive-into-function-calls.md`).

## Current Asya resiliency env vars (target for generation)

| Env Var | Type | Default | Retry concept |
|---------|------|---------|---------------|
| `ASYA_RESILIENCY_RETRY_POLICY` | "constant"\|"exponential" | "exponential" | Backoff strategy |
| `ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS` | int | 3 | Max attempts |
| `ASYA_RESILIENCY_RETRY_INITIAL_INTERVAL` | duration | "1s" | Backoff strategy |
| `ASYA_RESILIENCY_RETRY_MAX_INTERVAL` | duration | "300s" | Backoff strategy |
| `ASYA_RESILIENCY_RETRY_BACKOFF_COEFFICIENT` | float | 2.0 | Backoff strategy |
| `ASYA_RESILIENCY_RETRY_JITTER` | bool | true | Backoff strategy |
| `ASYA_RESILIENCY_NON_RETRYABLE_ERRORS` | csv | (none) | Exception filter |
| `ASYA_RESILIENCY_ACTOR_TIMEOUT` | duration | "5m" | Per-call timeout |

Not yet implemented: cumulative time window across all retry attempts.

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

### Feasibility of static YAML config for arg extraction

- **stamina, opnieuw, timeout_decorator**: Plain kwargs — trivially extractable via `kwarg_name -> env_var` mapping
- **backoff**: Needs positional arg support + first arg is a function reference (`backoff.expo`)
- **tenacity**: Impossible without AST evaluator — `stop_after_attempt(3)` is a function call returning a strategy object

Conclusion: static config covers ~60% of libraries (flat kwargs). The rest need per-library extractors or a first-party SDK approach. See [n67c] for the broader decorator strategy discussion.
